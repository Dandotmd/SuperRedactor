"""Apply a per-sheet column config to sheets, producing redacted copies
and a real→fake mapping.

Fake values are shared per redaction type across the whole run, so the
same real value gets the same fake wherever it appears (keeps joins
between sheets intact, e.g. an ID used in two sheets).
"""

from app.engine.fakers import FakeGenerator
from app.engine.readers import Sheet

# config shape: {sheet_name: {column_name: redaction_type | "drop"}}
Config = dict[str, dict[str, str]]
# mapping shape: {sheet_name: {column_name: {real: fake}}}
Mapping = dict[str, dict[str, dict[str, str]]]


def redact(sheets: list[Sheet], config: Config) -> tuple[list[Sheet], Mapping]:
    generators: dict[str, FakeGenerator] = {}
    by_type: dict[str, dict[str, str]] = {}  # col_type -> {real: fake}
    mapping: Mapping = {}
    out: list[Sheet] = []

    def fake_for(col_type: str, real: str) -> str:
        gen = generators.get(col_type)
        if gen is None:
            gen = generators[col_type] = FakeGenerator(col_type)
        values = by_type.setdefault(col_type, {})
        if real not in values:
            values[real] = gen.next(real)
        return values[real]

    for sheet in sheets:
        sheet_config = config.get(sheet.name, {})
        for col in sheet_config:
            if col not in sheet.headers:
                raise ValueError(f"No such column {col!r} in sheet {sheet.name!r}")

        drop_idx = {sheet.headers.index(c) for c, a in sheet_config.items() if a == "drop"}
        redact_idx = {
            sheet.headers.index(c): a for c, a in sheet_config.items() if a != "drop"
        }

        headers = [h for i, h in enumerate(sheet.headers) if i not in drop_idx]
        rows = []
        for row in sheet.rows:
            new_row = []
            for i, cell in enumerate(row):
                if i in drop_idx:
                    continue
                if i in redact_idx and cell != "":
                    col_type = redact_idx[i]
                    fake = fake_for(col_type, cell)
                    mapping.setdefault(sheet.name, {}).setdefault(
                        sheet.headers[i], {}
                    )[cell] = fake
                    new_row.append(fake)
                else:
                    new_row.append(cell)
            rows.append(new_row)
        out.append(Sheet(name=sheet.name, headers=headers, rows=rows))

    return out, mapping
