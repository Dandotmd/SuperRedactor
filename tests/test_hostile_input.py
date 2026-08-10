"""Regressions for inputs that crashed the app or corrupted data.

Each case was found by adversarial testing against real-world file quirks:
Mac line endings, pasted documents in a cell, Excel's "Unicode Text"
export, filenames with smart punctuation, and hostile spreadsheet formulas.
"""

import io

import pytest
from openpyxl import load_workbook

from app.engine.cleaners import analyze, apply_fixes
from app.engine.readers import Sheet, read_file
from app.engine.writers import write_csv, write_xlsx


def by_kind(findings, kind):
    return [f for f in findings if f.kind == kind]


# ---- parsing quirks -------------------------------------------------------

def test_classic_mac_cr_only_line_endings():
    data = b"name,score\rAda,88\rGrace,91\r"
    sheets = read_file("mac.csv", data)
    assert sheets[0].headers == ["name", "score"]
    assert sheets[0].rows == [["Ada", "88"], ["Grace", "91"]]


def test_cell_larger_than_the_csv_field_limit():
    big = "x" * 200_000
    data = f"name,notes\nAda,{big}\n".encode()
    sheets = read_file("big.csv", data)
    assert sheets[0].rows[0][1] == big


def test_utf16_csv_is_decoded_not_mangled():
    data = "name,city\nJosé,Köln\n".encode("utf-16")
    sheets = read_file("x.csv", data)
    assert sheets[0].headers == ["name", "city"]
    assert sheets[0].rows == [["José", "Köln"]]


def test_utf16_without_bom_is_decoded():
    data = "name,city\nJosé,Köln\n".encode("utf-16-le")
    sheets = read_file("x.csv", data)
    assert sheets[0].headers == ["name", "city"]


# ---- formulas must never execute in output --------------------------------

FORMULAS = ["=cmd|'/c calc'!A1", "@SUM(1+1)", "+1+1", "-cmd|calc"]


def test_csv_output_never_starts_a_cell_with_a_formula_character():
    sheet = Sheet(name="S", headers=["note"], rows=[[f] for f in FORMULAS])
    text = write_csv(sheet).decode()
    for line in text.splitlines()[1:]:
        assert not line.lstrip('"').startswith(("=", "@", "+", "-")), line


def test_xlsx_output_stores_formulas_as_text_not_live_formulas():
    sheet = Sheet(name="S", headers=["note"], rows=[[f] for f in FORMULAS])
    wb = load_workbook(io.BytesIO(write_xlsx([sheet])))
    ws = wb["S"]
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            assert cell.data_type != "f", f"{cell.value} is a live formula"


def test_negative_numbers_survive_unharmed():
    sheet = Sheet(name="S", headers=["amount"], rows=[["-5"], ["-12.5"]])
    lines = write_csv(sheet).decode().splitlines()
    assert lines[1:] == ["-5", "-12.5"]


# ---- cleaners must not delete real data -----------------------------------

def test_sparse_trailing_rows_are_kept():
    # A newly enrolled student with only a name filled in is not a footnote
    sheets = [
        Sheet(
            name="S",
            headers=["Student", "Grade", "Score"],
            rows=[
                ["Ada", "A", "90"],
                ["Grace", "B", "80"],
                ["Alan", "A", "95"],
                ["Kay", "", ""],
            ],
        )
    ]
    cleaned = apply_fixes(sheets, {f.id for f in analyze(sheets)})
    assert [r[0] for r in cleaned[0].rows] == ["Ada", "Grace", "Alan", "Kay"]


def test_keyword_footer_rows_are_still_removed():
    sheets = [
        Sheet(
            name="S",
            headers=["Student", "Score"],
            rows=[["Ada", "90"], ["Grace", "80"], ["Total", "170"]],
        )
    ]
    cleaned = apply_fixes(sheets, {f.id for f in analyze(sheets)})
    assert [r[0] for r in cleaned[0].rows] == ["Ada", "Grace"]


def test_country_code_na_is_not_treated_as_missing():
    sheets = [
        Sheet(
            name="S",
            headers=["Student", "Region"],
            rows=[["Ada", "NA"], ["Grace", "GB"], ["Alan", "NA"]],
        )
    ]
    findings = analyze(sheets)
    assert by_kind(findings, "missing_values") == []
    cleaned = apply_fixes(sheets, {f.id for f in findings})
    assert [r[1] for r in cleaned[0].rows] == ["NA", "GB", "NA"]
    assert cleaned[0].headers == ["Student", "Region"]


def test_none_as_a_category_is_not_treated_as_missing():
    sheets = [
        Sheet(
            name="S",
            headers=["Student", "Allergy"],
            rows=[["Ada", "None"], ["Grace", "Peanut"], ["Alan", "None"]],
        )
    ]
    assert by_kind(analyze(sheets), "missing_values") == []


def test_unambiguous_missing_markers_still_normalized():
    sheets = [
        Sheet(
            name="S",
            headers=["Student", "Score"],
            rows=[["Ada", "N/A"], ["Grace", "NULL"], ["Alan", "88"]],
        )
    ]
    findings = analyze(sheets)
    assert by_kind(findings, "missing_values")[0].count == 2


# ---- excel formulas with no cached value ----------------------------------

def test_xlsx_formula_without_cached_value_reads_as_its_formula():
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "S"
    ws.append(["Student", "Total"])
    ws.append(["Ada", "=1+1"])
    ws.append(["Grace", "=2+2"])
    buf = io.BytesIO()
    wb.save(buf)

    sheets = read_file("calc.xlsx", buf.getvalue())
    assert [r[1] for r in sheets[0].rows] == ["=1+1", "=2+2"]


# ---- performance ----------------------------------------------------------

def test_analyze_is_fast_on_a_large_file():
    import time

    rows = [
        [f"Person {i}", "3/12/2024", f"{i}", "note", "x"] for i in range(50_000)
    ]
    sheets = [
        Sheet(name="S", headers=["name", "seen", "n", "note", "z"], rows=rows)
    ]
    start = time.monotonic()
    analyze(sheets)
    assert time.monotonic() - start < 8.0
