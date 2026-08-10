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


def test_unsupported_extension_raises():
    import pytest

    with pytest.raises(ValueError, match="Unsupported"):
        read_file("data.parquet", b"whatever")
