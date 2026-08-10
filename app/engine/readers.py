"""Parse uploaded CSV/XLSX bytes into a normalized sheet structure."""

import csv
import io
import re
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


def _normalize(headers: list[str], rows: list[list[str]]) -> Sheet:
    """Make every row exactly as wide as the header row. Short rows are
    padded; when a data row is wider than the headers, the headers are
    extended instead of hiding the extra cells (a hidden cell could carry
    PII the user never sees or redacts)."""
    width = max([len(headers), *(len(r) for r in rows)] if rows else [len(headers)])
    headers = headers + [f"extra_column_{i + 1}" for i in range(len(headers), width)]
    rows = [row + [""] * (width - len(row)) for row in rows]

    # Column selection is keyed by header name, so names must be unique and
    # non-empty or some columns could never be addressed for redaction.
    seen: dict[str, int] = {}
    unique = []
    for i, name in enumerate(headers):
        name = name.strip() or f"column_{i + 1}"
        count = seen.get(name, 0) + 1
        seen[name] = count
        unique.append(name if count == 1 else f"{name} ({count})")
    return unique, rows


def _decode(data: bytes) -> str:
    # Federal exports are frequently cp1252/Latin-1 rather than UTF-8.
    # latin-1 is the terminal fallback: it accepts any byte sequence.
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise AssertionError("unreachable")


def _sniff_delimiter(text: str) -> str:
    # Federal data isn't always comma-separated (FEC uses "|", BLS uses tabs).
    sample = text[:65536]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


_DATA_CELL = re.compile(r"^-?[\d,.]+$|^\d{4}-\d{2}-\d{2}|^\d{1,2}/\d{1,2}/\d{2,4}$")


def _has_header(first_row: list[str]) -> bool:
    # Headers are essentially never numbers or dates; data rows usually
    # contain at least one. Bias toward "has a header" — the wrong guess
    # there only shows odd column names, while treating a real header as
    # data is harmless (it just gets redacted along with everything else).
    return not any(_DATA_CELL.match(cell) for cell in first_row if cell)


def _read_csv(data: bytes) -> Sheet:
    text = _decode(data)
    reader = csv.reader(io.StringIO(text), delimiter=_sniff_delimiter(text))
    rows = [row for row in reader if row]
    if rows and _has_header(rows[0]):
        headers, body = rows[0], rows[1:]
    else:
        headers = [f"column_{i + 1}" for i in range(len(rows[0]) if rows else 0)]
        body = rows
    body = [[_cell(v) for v in row] for row in body]
    headers, body = _normalize(headers, body)
    return Sheet(name="Sheet1", headers=headers, rows=body)


def _read_xlsx(data: bytes) -> list[Sheet]:
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    sheets = []
    for ws in wb.worksheets:
        rows = [[_cell(v) for v in row] for row in ws.iter_rows(values_only=True)]
        headers = rows[0] if rows else []
        headers, body = _normalize(headers, rows[1:])
        sheets.append(Sheet(name=ws.title, headers=headers, rows=body))
    return sheets
