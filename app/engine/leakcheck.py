"""Warn when a value being redacted in one column survives in a column the
user chose to keep.

Column-level redaction can't see that the name in 'name' is repeated in
'emergency_contact' or quoted inside a 'notes' sentence. Someone who ticks
the suggested columns and downloads would ship the very data they meant to
hide, so this check runs before the download and says so plainly.
"""

from dataclasses import dataclass, field

# Substring scanning is the expensive half, so it is bounded. Exact-cell
# matching is a cheap set lookup and always runs over every row.
MAX_TRACKED_VALUES = 2000
MAX_SUBSTRING_ROWS = 20_000
MIN_SUBSTRING_LENGTH = 4
MAX_SAMPLES = 3


@dataclass
class Leak:
    sheet: str
    redacted_column: str
    kept_column: str
    count: int
    samples: list[str] = field(default_factory=list)


def find_weak_columns(sheets, config: dict[str, dict[str, str]]) -> list[str]:
    """Columns whose possible replacements are too few to hide anything —
    26 single-letter grade codes have only 26 possible fakes, so every fake
    is somebody's real grade."""
    from app.engine.fakers import estimate_pool

    weak: list[str] = []
    for sheet in sheets:
        for column, action in config.get(sheet.name, {}).items():
            if action == "drop" or column not in sheet.headers:
                continue
            index = sheet.headers.index(column)
            values = _distinct_values(sheet.rows, index)
            if not values:
                continue
            if len(values) * 2 > estimate_pool(action, values) and column not in weak:
                weak.append(column)
    return weak


def find_leaks(sheets, config: dict[str, dict[str, str]]) -> list[Leak]:
    leaks: list[Leak] = []
    for sheet in sheets:
        actions = config.get(sheet.name, {})
        redacted = [c for c, a in actions.items() if a != "drop" and c in sheet.headers]
        if not redacted:
            continue
        kept = [
            h for h in sheet.headers
            if h not in actions  # neither redacted nor dropped
        ]
        if not kept:
            continue

        idx = {h: i for i, h in enumerate(sheet.headers)}
        for column in redacted:
            values = _distinct_values(sheet.rows, idx[column])
            if not values:
                continue
            long_values = [v for v in values if len(v) >= MIN_SUBSTRING_LENGTH]
            for kept_column in kept:
                leak = _scan_column(
                    sheet, idx[kept_column], values, long_values
                )
                if leak is None:
                    continue
                count, samples = leak
                leaks.append(
                    Leak(
                        sheet=sheet.name,
                        redacted_column=column,
                        kept_column=kept_column,
                        count=count,
                        samples=samples,
                    )
                )
    return leaks


def _distinct_values(rows, index: int) -> set[str]:
    values: set[str] = set()
    for row in rows:
        value = row[index].strip()
        if value:
            values.add(value)
            if len(values) >= MAX_TRACKED_VALUES:
                break
    return values


def _scan_column(sheet, index: int, values: set[str], long_values: list[str]):
    count = 0
    samples: list[str] = []
    for row_number, row in enumerate(sheet.rows):
        cell = row[index].strip()
        if not cell:
            continue
        hit = None
        if cell in values:
            hit = cell
        elif row_number < MAX_SUBSTRING_ROWS:
            for value in long_values:
                if value in cell:
                    hit = value
                    break
        if hit is not None:
            count += 1
            if hit not in samples and len(samples) < MAX_SAMPLES:
                samples.append(hit)
    return (count, samples) if count else None
