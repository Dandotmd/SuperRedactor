"""Parse uploaded CSV/XLSX bytes into a normalized sheet structure."""

import csv
import io
import re
import sys
from dataclasses import dataclass, field

from openpyxl import load_workbook

# A single cell can legitimately hold a pasted document; the stdlib default
# of 128 KB rejects those outright.
csv.field_size_limit(min(sys.maxsize, 2**31 - 1))


@dataclass
class Sheet:
    name: str
    headers: list[str]
    rows: list[list[str]] = field(default_factory=list)


def read_file(filename: str, data: bytes) -> list[Sheet]:
    """Parse an upload into sheets. Every failure raises ValueError with a
    message written for someone who has never heard of an encoding."""
    lower = filename.lower()
    if not data.strip():
        raise ValueError("This file is empty — there's nothing to work with.")

    if lower.endswith(".xls"):
        raise ValueError(
            "Excel 97-2003 files (.xls) aren't supported. Open the file in Excel "
            "and use File → Save As → Excel Workbook (.xlsx), then try again."
        )
    if lower.endswith(".csv") or lower.endswith(".txt") or lower.endswith(".tsv"):
        sheets = [_read_csv(data)]
    elif lower.endswith(".xlsx") or lower.endswith(".xlsm"):
        sheets = _read_xlsx(data)
    elif lower.endswith(".zip"):
        raise ValueError(
            "This is a ZIP folder, not a spreadsheet. Unzip it first (double-click "
            "it), then choose the .csv or .xlsx file inside."
        )
    else:
        raise ValueError(
            "This tool reads spreadsheet files: CSV (.csv) or Excel (.xlsx). "
            f"'{filename}' is something else — try exporting your data as CSV first."
        )

    if not any(s.rows for s in sheets):
        raise ValueError(
            "This file has column headings but no data rows underneath them, "
            "so there's nothing to process."
        )
    return sheets


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
    """Decode spreadsheet bytes, then normalize line endings.

    Excel writes UTF-16 for "Unicode Text", older exports are cp1252, and
    classic-Mac tools still emit CR-only line endings. latin-1 is the
    terminal fallback: it accepts any byte sequence, so decoding never
    fails outright.
    """
    text = None
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            text = data.decode("utf-16")
        except UnicodeDecodeError:
            text = None
    if text is None:
        # UTF-16 without a BOM shows up as every other byte being NUL.
        head = data[:4096]
        if head.count(0) > len(head) // 4:
            for encoding in ("utf-16-le", "utf-16-be"):
                try:
                    candidate = data.decode(encoding)
                except UnicodeDecodeError:
                    continue
                if "\x00" not in candidate:
                    text = candidate
                    break
    if text is None:
        for encoding in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                text = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
    if text is None:  # pragma: no cover - latin-1 accepts anything
        raise AssertionError("unreachable")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _sniff_delimiter(text: str) -> str:
    # Federal data isn't always comma-separated (FEC uses "|", BLS uses tabs).
    sample = text[:65536]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


# Shapes a column heading is essentially never written in. Getting this
# wrong in the "it's a header" direction is dangerous: the header row is not
# part of the data, so nothing in it is ever redacted. A roster whose first
# person is mistaken for the headings would ship their name and SSN inside a
# file labelled "redacted".
_VALUE_SHAPES = (
    re.compile(r"^-?[\d,.]+$"),                     # 1,234.50
    re.compile(r"^\d{4}-\d{2}-\d{2}"),              # 2024-03-12
    re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$"),       # 3/12/2024
    re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$"), # ada@school.edu
    re.compile(r"^[$€£]\s?[\d,]+"),                 # $1,234
    re.compile(r"^\+?[\d][\d\s().-]{6,}$"),         # 111-22-3333, phone
    re.compile(r"^\d{5,}$"),                        # long id run
)


def _looks_like_a_value(cell: str) -> bool:
    text = cell.strip()
    return bool(text) and any(shape.match(text) for shape in _VALUE_SHAPES)


def _has_header(first_row: list[str]) -> bool:
    return not any(_looks_like_a_value(cell) for cell in first_row)


def _read_csv(data: bytes) -> Sheet:
    text = _decode(data)
    head = text.lstrip()[:200].lower()
    if head.startswith("<!doctype html") or head.startswith("<html") or "<body" in head:
        raise ValueError(
            "This looks like a saved web page, not a spreadsheet. It usually means "
            "a download failed or a login page was saved by mistake — try "
            "downloading the file again."
        )
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
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        # openpyxl raises a wide variety of low-level errors (zip, XML, key)
        # for damaged or password-protected workbooks.
        raise ValueError(
            "This Excel file could not be opened. It may be damaged, "
            "password-protected, or not really an Excel file. Try opening it in "
            "Excel and saving a fresh copy."
        )
    sheets = []
    for ws in wb.worksheets:
        rows = [[_cell(v) for v in row] for row in ws.iter_rows(values_only=True)]
        headers = rows[0] if rows else []
        headers, body = _normalize(headers, rows[1:])
        sheets.append(Sheet(name=ws.title, headers=headers, rows=body))

    if any(_blank_columns(s) for s in sheets):
        _fill_from_formulas(data, sheets)
    return sheets


def _blank_columns(sheet: Sheet) -> list[int]:
    if not sheet.rows:
        return []
    return [
        i
        for i in range(len(sheet.headers))
        if all(not row[i].strip() for row in sheet.rows)
    ]


def _fill_from_formulas(data: bytes, sheets: list[Sheet]) -> None:
    """A workbook saved by a script or a web exporter often has no cached
    results for its formulas, so those columns read as empty and later look
    deletable. Fall back to the formula text so the column survives. Only
    reached when a column is entirely empty, so the extra read is rare.
    """
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=False)
    except Exception:
        return
    by_name = {ws.title: ws for ws in wb.worksheets}
    for sheet in sheets:
        blanks = _blank_columns(sheet)
        ws = by_name.get(sheet.name)
        if not blanks or ws is None:
            continue
        raw = [[_cell(v) for v in row] for row in ws.iter_rows(values_only=True)]
        for row_number, row in enumerate(sheet.rows, start=1):
            if row_number >= len(raw):
                break
            for i in blanks:
                if i < len(raw[row_number]):
                    row[i] = raw[row_number][i]
