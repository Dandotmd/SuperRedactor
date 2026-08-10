"""Serialize sheets back to CSV or XLSX bytes (values only)."""

import csv
import io

from openpyxl import Workbook

from app.engine.readers import Sheet


def write_csv(sheet: Sheet) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(sheet.headers)
    writer.writerows(sheet.rows)
    return buf.getvalue().encode("utf-8")


def write_xlsx(sheets: list[Sheet]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for sheet in sheets:
        ws = wb.create_sheet(title=sheet.name)
        ws.append(sheet.headers)
        for row in sheet.rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
