"""Parse uploaded CSV/XLSX bytes into a normalized sheet structure."""

import csv
import io
from dataclasses import dataclass, field

from openpyxl import load_workbook


@dataclass
class Sheet:
    name: str
    headers: list[str]
    rows: list[list[str]] = field(default_factory=list)


def read_file(filename: str, data: bytes) -> list[Sheet]:
    lower = filename.lower()
    if lower.endswith(".csv"):
        return [_read_csv(data)]
    if lower.endswith(".xlsx"):
        return _read_xlsx(data)
    raise ValueError(f"Unsupported file type: {filename} (expected .csv or .xlsx)")


def _cell(value) -> str:
    return "" if value is None else str(value)


def _read_csv(data: bytes) -> Sheet:
    text = data.decode("utf-8-sig")
    reader = csv.reader(io.StringIO(text))
    rows = [row for row in reader if row]
    headers = rows[0] if rows else []
    body = [[_cell(v) for v in row] for row in rows[1:]]
    return Sheet(name="Sheet1", headers=headers, rows=body)


def _read_xlsx(data: bytes) -> list[Sheet]:
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    sheets = []
    for ws in wb.worksheets:
        rows = [[_cell(v) for v in row] for row in ws.iter_rows(values_only=True)]
        headers = rows[0] if rows else []
        sheets.append(Sheet(name=ws.title, headers=headers, rows=rows[1:]))
    return sheets
