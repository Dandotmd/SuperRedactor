"""Apply a per-sheet column config to sheets, producing redacted copies
and a real→fake mapping.

Fake values are shared per redaction type across the whole run, so the
same real value gets the same fake wherever it appears (keeps joins
between sheets intact, e.g. an ID used in two sheets).
"""

from app.engine.fakers import FakeGenerator, normalize_value
from app.engine.readers import Sheet

# config shape: {sheet_name: {column_name: redaction_type | "drop"}}
Config = dict[str, dict[str, str]]
# mapping shape: {sheet_name: {column_name: {real: fake}}}
Mapping = dict[str, dict[str, dict[str, str]]]


def _real_values(sheets: list[Sheet], config: Config) -> set[str]:
    """Every real value the user asked to be rid of — replaced or removed —
    normalized.

    Normalized because "  Mary  " and "Mary" are the same person's name to
    everyone except an exact string comparison: without this, a padded
    entry leaves the plain spelling free for the generator to hand to
    somebody else, and a real name lands in the redacted file.

    Dropped columns count too. Their values are real data the user chose to
    delete, so handing one back as another row's fake puts it right back in
    the file.
    """
    values: set[str] = set()
    for sheet in sheets:
        for column, action in config.get(sheet.name, {}).items():
            if column not in sheet.headers:
                continue
            index = sheet.headers.index(column)
            for row in sheet.rows:
                cell = normalize_value(row[index])
                if cell:
                    values.add(cell)
    return values


def redact(
    sheets: list[Sheet], config: Config, report: bool = False
) -> tuple[list[Sheet], Mapping] | tuple[list[Sheet], Mapping, list[str]]:
    known_sheets = {s.name for s in sheets}
    for name in config:
        if name not in known_sheets:
            raise ValueError(f"No sheet named {name!r} in this file")

    generators: dict[str, FakeGenerator] = {}
    by_type: dict[str, dict[str, str]] = {}  # col_type -> {real: fake}
    issued: set[str] = set()
    forbidden = _real_values(sheets, config)
    mapping: Mapping = {}
    out: list[Sheet] = []
    weak_columns: list[str] = []

    def fake_for(col_type: str, real: str) -> str:
        gen = generators.get(col_type)
        if gen is None:
            gen = generators[col_type] = FakeGenerator(
                col_type, issued=issued, forbidden=forbidden
            )
        values = by_type.setdefault(col_type, {})
        # Keyed by normalized value so "Ada Lovelace", "  Ada Lovelace  "
        # and "ADA LOVELACE" are one person with one replacement — anything
        # else breaks joins and burns three entries of the fake pool.
        key = normalize_value(real)
        if key not in values:
            values[key] = gen.next(real)
        return values[key]

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
                    if (
                        generators[col_type].exhausted
                        and sheet.headers[i] not in weak_columns
                    ):
                        weak_columns.append(sheet.headers[i])
                    mapping.setdefault(sheet.name, {}).setdefault(
                        sheet.headers[i], {}
                    )[cell] = fake
                    new_row.append(fake)
                else:
                    new_row.append(cell)
            rows.append(new_row)
        out.append(Sheet(name=sheet.name, headers=headers, rows=rows))

    if not report:
        return out, mapping
    warnings = [
        f"'{column}' has too few different values to hide — some replacements "
        f"reuse a value that really appears in this column. Consider removing "
        f"the column instead."
        for column in weak_columns
    ]
    return out, mapping, warnings
