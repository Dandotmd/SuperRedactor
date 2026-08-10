from app.engine.cleaners import analyze, apply_fixes
from app.engine.readers import Sheet


def sheet(headers, rows, name="Sheet1"):
    return Sheet(name=name, headers=headers, rows=rows)


def finding_ids(findings):
    return {f.id for f in findings}


def by_kind(findings, kind):
    return [f for f in findings if f.kind == kind]


# ---- title rows -----------------------------------------------------------

def messy_report():
    # As readers.py would deliver a file whose real header is on row 3:
    # the title lands in headers[0] and the rest become column_N.
    return [
        sheet(
            ["Quarterly Staff Report", "column_2", "column_3"],
            [
                ["", "", ""],
                ["Name", "Email", "Score"],
                ["Sarah Chen", "s@x.org", "88"],
                ["Bob Ray", "b@x.org", "91"],
            ],
        )
    ]


def test_detects_and_removes_title_rows():
    findings = analyze(messy_report())
    tf = by_kind(findings, "title_rows")
    assert len(tf) == 1 and tf[0].count == 2
    cleaned = apply_fixes(messy_report(), finding_ids(findings))
    assert cleaned[0].headers == ["Name", "Email", "Score"]
    assert cleaned[0].rows == [["Sarah Chen", "s@x.org", "88"], ["Bob Ray", "b@x.org", "91"]]


def test_clean_file_has_no_title_row_finding():
    sheets = [sheet(["Name", "Score"], [["Sarah", "88"], ["Bob", "91"]])]
    assert by_kind(analyze(sheets), "title_rows") == []


# ---- trailing junk --------------------------------------------------------

def test_removes_total_and_source_rows_at_bottom():
    sheets = [
        sheet(
            ["Name", "Region", "Sales"],
            [
                ["Sarah", "West", "100"],
                ["Bob", "East", "200"],
                ["Total", "", "300"],
                ["Source: internal CRM", "", ""],
            ],
        )
    ]
    findings = analyze(sheets)
    tf = by_kind(findings, "trailing_junk")
    assert len(tf) == 1 and tf[0].count == 2
    cleaned = apply_fixes(sheets, finding_ids(findings))
    assert [r[0] for r in cleaned[0].rows] == ["Sarah", "Bob"]


# ---- blank rows / columns -------------------------------------------------

def test_removes_blank_rows_and_columns():
    sheets = [
        sheet(
            ["Name", "column_2", "Score"],
            [
                ["Sarah", "", "88"],
                ["", "", ""],
                ["Bob", "", "91"],
            ],
        )
    ]
    findings = analyze(sheets)
    assert by_kind(findings, "blank_rows")[0].count == 1
    assert by_kind(findings, "blank_columns")[0].count == 1
    cleaned = apply_fixes(sheets, finding_ids(findings))
    assert cleaned[0].headers == ["Name", "Score"]
    assert cleaned[0].rows == [["Sarah", "88"], ["Bob", "91"]]


# ---- duplicates -----------------------------------------------------------

def test_removes_exact_duplicate_rows_keeping_first():
    sheets = [
        sheet(["Name"], [["Sarah"], ["Bob"], ["Sarah"], ["Sarah"]])
    ]
    findings = analyze(sheets)
    assert by_kind(findings, "duplicate_rows")[0].count == 2
    cleaned = apply_fixes(sheets, finding_ids(findings))
    assert cleaned[0].rows == [["Sarah"], ["Bob"]]


# ---- whitespace -----------------------------------------------------------

def test_normalizes_whitespace():
    sheets = [
        sheet(["Name"], [["  Sarah  Chen "], ["Bob Ray"], ["Fine"]])
    ]
    findings = analyze(sheets)
    assert by_kind(findings, "whitespace")[0].count == 2
    cleaned = apply_fixes(sheets, finding_ids(findings))
    assert cleaned[0].rows == [["Sarah Chen"], ["Bob Ray"], ["Fine"]]


# ---- missing-value markers ------------------------------------------------

def test_normalizes_missing_value_markers():
    sheets = [
        sheet(["Score"], [["88"], ["N/A"], ["null"], ["--"], ["ok"]])
    ]
    findings = analyze(sheets)
    assert by_kind(findings, "missing_values")[0].count == 3
    cleaned = apply_fixes(sheets, finding_ids(findings))
    assert cleaned[0].rows == [["88"], [""], [""], [""], ["ok"]]


# ---- numbers stored as text -----------------------------------------------

def test_strips_currency_and_thousands_separators():
    sheets = [
        sheet(
            ["Amount", "Code"],
            [["$1,234.56", "A1"], ["(2,500)", "B2"], ["300", "C3"]],
        )
    ]
    findings = analyze(sheets)
    nf = by_kind(findings, "numbers_as_text")
    assert len(nf) == 1 and nf[0].column == "Amount"
    cleaned = apply_fixes(sheets, finding_ids(findings))
    assert [r[0] for r in cleaned[0].rows] == ["1234.56", "-2500", "300"]
    assert [r[1] for r in cleaned[0].rows] == ["A1", "B2", "C3"]


def test_plain_number_column_untouched():
    sheets = [sheet(["Score"], [["88"], ["91"], ["75"]])]
    assert by_kind(analyze(sheets), "numbers_as_text") == []


# ---- mixed date formats ---------------------------------------------------

def test_normalizes_mixed_date_formats_to_iso():
    sheets = [
        sheet(
            ["Seen", "Notes"],
            [
                ["3/12/2024", "ok"],
                ["2024-03-15", "meh"],
                ["Mar 20, 2024", "fine"],
            ],
        )
    ]
    findings = analyze(sheets)
    df = by_kind(findings, "date_formats")
    assert len(df) == 1 and df[0].column == "Seen"
    cleaned = apply_fixes(sheets, finding_ids(findings))
    assert [r[0] for r in cleaned[0].rows] == ["2024-03-12", "2024-03-15", "2024-03-20"]
    assert [r[1] for r in cleaned[0].rows] == ["ok", "meh", "fine"]


def test_uniform_iso_dates_not_flagged():
    sheets = [sheet(["Seen"], [["2024-03-12"], ["2024-03-15"], ["2024-04-01"]])]
    assert by_kind(analyze(sheets), "date_formats") == []


# ---- selective application ------------------------------------------------

def test_disabled_fixes_are_not_applied():
    sheets = [
        sheet(["Name"], [["  Sarah "], ["Bob"], ["Bob"]])
    ]
    findings = analyze(sheets)
    keep = {f.id for f in findings if f.kind != "duplicate_rows"}
    cleaned = apply_fixes(sheets, keep)
    assert cleaned[0].rows == [["Sarah"], ["Bob"], ["Bob"]]


def test_finding_ids_are_stable_across_calls():
    assert finding_ids(analyze(messy_report())) == finding_ids(analyze(messy_report()))
