"""Apply a per-sheet column config to sheets, producing redacted copies
and a real→fake mapping.

Fake values are shared per redaction type across the whole run, so the
same real value gets the same fake wherever it appears (keeps joins
between sheets intact, e.g. an ID used in two sheets).
"""

from dataclasses import dataclass

from app.engine.fakers import FakeGenerator, normalize_value
from app.engine.readers import Sheet

# config shape: {sheet_name: {column_name: redaction_type | "drop"}}
@dataclass(frozen=True)
class WeakColumn:
    """A column the generator could not hide: it ran out of replacements
    that weren't already somebody's real value."""

    sheet: str
    column: str


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
                # Both forms, so the check works whichever type later asks
                cell = row[index]
                for form in (normalize_value(cell), normalize_value(cell, action)):
                    if form:
                        values.add(form)
    return values


def redact(
    sheets: list[Sheet], config: Config, report: bool = False, seed: int | None = None
) -> tuple[list[Sheet], Mapping] | tuple[list[Sheet], Mapping, list["WeakColumn"]]:
    """Replace the configured columns with fake values.

    `seed` makes a run reproducible. The warning shown before the download
    is produced by running this very function, so without a seed the check
    would be measuring a *different* random run than the one the user then
    downloads — fine most of the time, wrong exactly when the pool is
    marginal and the warning matters most.
    """
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
    weak_columns: list["WeakColumn"] = []

    def fake_for(col_type: str, real: str) -> tuple[str, bool]:
        gen = generators.get(col_type)
        if gen is None:
            gen = generators[col_type] = FakeGenerator(
                col_type,
                seed=None if seed is None else seed + len(generators),
                issued=issued,
                forbidden=forbidden,
            )
        values = by_type.setdefault(col_type, {})
        # Keyed by normalized value so "Ada Lovelace", "  Ada Lovelace  "
        # and "ADA LOVELACE" are one person with one replacement — anything
        # else breaks joins and burns three entries of the fake pool.
        key = normalize_value(real, col_type)
        if key not in values:
            values[key] = gen.next(real)
            return values[key], gen.last_exhausted
        return values[key], False

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
                    fake, ran_short = fake_for(col_type, cell)
                    if ran_short:
                        weak = WeakColumn(sheet=sheet.name, column=sheet.headers[i])
                        if weak not in weak_columns:
                            weak_columns.append(weak)
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
    return out, mapping, weak_columns
