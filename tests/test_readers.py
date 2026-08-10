import io

from openpyxl import Workbook

from app.engine.readers import read_file


def make_xlsx(sheets: dict[str, list[list]]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(title=name)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_reads_csv_into_single_sheet():
    data = b"name,email\nSarah Chen,sarah@example.com\nBob Ray,bob@example.com\n"
    sheets = read_file("people.csv", data)
    assert len(sheets) == 1
    assert sheets[0].headers == ["name", "email"]
    assert sheets[0].rows == [
        ["Sarah Chen", "sarah@example.com"],
        ["Bob Ray", "bob@example.com"],
    ]


def test_reads_xlsx_with_multiple_sheets():
    data = make_xlsx(
        {
            "Students": [["id", "name"], [101, "Sarah Chen"]],
            "Sessions": [["student_id", "date"], [101, "2026-01-05"]],
        }
    )
    sheets = read_file("export.xlsx", data)
    assert [s.name for s in sheets] == ["Students", "Sessions"]
    assert sheets[0].headers == ["id", "name"]
    assert sheets[0].rows == [["101", "Sarah Chen"]]
    assert sheets[1].rows == [["101", "2026-01-05"]]


def test_empty_cells_become_empty_strings():
    data = b"name,phone\nSarah,\n,555-1234\n"
    sheets = read_file("x.csv", data)
    assert sheets[0].rows == [["Sarah", ""], ["", "555-1234"]]


def test_reads_latin1_encoded_csv():
    # Census county files carry names like "Doña Ana" in Latin-1/cp1252
    data = "county,pop\nDoña Ana,220000\n".encode("cp1252")
    sheets = read_file("counties.csv", data)
    assert sheets[0].rows == [["Doña Ana", "220000"]]


def test_reads_utf8_csv_with_bom():
    data = "﻿name\nJosé\n".encode("utf-8")
    sheets = read_file("x.csv", data)
    assert sheets[0].headers == ["name"]
    assert sheets[0].rows == [["José"]]


def test_reads_pipe_delimited_csv():
    # FEC bulk downloads are pipe-delimited, with commas inside fields
    data = b"id|name|city\nH0AK00105|LAMB, THOMAS|WASILLA\n"
    sheets = read_file("cn.csv", data)
    assert sheets[0].headers == ["id", "name", "city"]
    assert sheets[0].rows == [["H0AK00105", "LAMB, THOMAS", "WASILLA"]]


def test_reads_tab_delimited_csv():
    data = b"name\temail\nSarah\ts@x.com\n"
    sheets = read_file("x.csv", data)
    assert sheets[0].rows == [["Sarah", "s@x.com"]]


def test_reads_semicolon_delimited_csv():
    data = b"name;score\nSarah;88\n"
    sheets = read_file("x.csv", data)
    assert sheets[0].rows == [["Sarah", "88"]]


def test_comma_csv_with_quoted_commas_still_comma_delimited():
    data = b'name,address\n"Ray, Bob","1 Main St, Apt 2"\n'
    sheets = read_file("x.csv", data)
    assert sheets[0].rows == [["Ray, Bob", "1 Main St, Apt 2"]]


def test_single_column_csv_parses():
    data = b"name\nSarah\nBob\n"
    sheets = read_file("x.csv", data)
    assert sheets[0].headers == ["name"]
    assert sheets[0].rows == [["Sarah"], ["Bob"]]


def test_short_rows_padded_to_header_width():
    data = b"name,email,score\nSarah,s@x.com\nBob\n"
    sheets = read_file("x.csv", data)
    assert sheets[0].rows == [["Sarah", "s@x.com", ""], ["Bob", "", ""]]


def test_long_rows_extend_headers_so_no_cell_is_hidden():
    data = b"name,score\nSarah,88,extra@leak.com\n"
    sheets = read_file("x.csv", data)
    assert sheets[0].headers == ["name", "score", "extra_column_3"]
    assert sheets[0].rows == [["Sarah", "88", "extra@leak.com"]]


def test_empty_header_names_get_placeholder_names():
    data = b"name,,score\nSarah,x,88\n"
    sheets = read_file("x.csv", data)
    assert sheets[0].headers == ["name", "column_2", "score"]


def test_duplicate_header_names_made_unique():
    # duplicate names would make column selection ambiguous — only the
    # first duplicate would ever get redacted
    data = b"name,name,score\nSarah,Chen,88\n"
    sheets = read_file("x.csv", data)
    assert sheets[0].headers == ["name", "name (2)", "score"]


def test_xlsx_whole_number_floats_read_without_trailing_point_zero():
    # Excel stores numbers as doubles; an ID column must not become "1001.0"
    data = make_xlsx({"S": [["id", "ratio"], [1001.0, 0.5]]})
    sheets = read_file("x.xlsx", data)
    assert sheets[0].rows == [["1001", "0.5"]]


def test_headerless_csv_gets_synthetic_headers_and_keeps_first_row():
    # FEC bulk files have no header row; the first record must stay data
    # (a "header" full of PII would never be redacted)
    data = (
        b"H0AK00105|LAMB, THOMAS|NNE|2020|AK\n"
        b"H0AL01055|CARL, JERRY LEE, JR|REP|2024|AL\n"
        b"H2AK01158|BEGICH, NICHOLAS|REP|2024|AK\n"
    )
    sheets = read_file("cn.csv", data)
    assert sheets[0].headers == [f"column_{i}" for i in range(1, 6)]
    assert len(sheets[0].rows) == 3
    assert sheets[0].rows[0][1] == "LAMB, THOMAS"


def test_unsupported_extension_raises():
    import pytest

    with pytest.raises(ValueError, match="Unsupported"):
        read_file("data.parquet", b"whatever")
