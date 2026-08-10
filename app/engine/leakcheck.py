"""Warn when a value being redacted survives somewhere the user is keeping.

Column-level redaction can't see that the name in 'Student' is repeated in
'Guardian', quoted inside a 'Notes' sentence, or sitting in the clear on
another sheet of the same workbook. Someone who ticks the suggested columns
and downloads would ship the very data they meant to hide, so this runs
before the download and says so plainly.

Matching is case-insensitive and spans the whole workbook, because a leak
that is reported as "1 cell" when three names are exposed is worse than no
report at all — it teaches people the warning can be trusted when it can't.
"""

from dataclasses import dataclass, field

# Exact-cell matching is a dictionary lookup and runs over every row of
# every sheet, so the "same value in two columns" case is always caught in
# full — there is no cap on values or rows.
#
# Finding a value quoted inside a sentence needs word-window lookups, which
# cost more per cell, so that half stops after a bounded number of rows.
MAX_SUBSTRING_ROWS = 200_000
MIN_SUBSTRING_LENGTH = 4
MAX_VALUE_WORDS = 5
MAX_SAMPLES = 3

_EDGE_PUNCTUATION = " \t.,;:!?()[]{}\"'"


@dataclass
class Leak:
    sheet: str
    redacted_column: str
    kept_column: str
    count: int
    samples: list[str] = field(default_factory=list)


def _key(value: str) -> str:
    """The form two spellings of the same value share. Runs of whitespace
    collapse so 'Ida  Wells' in the roster still matches 'Ida Wells' in a
    sentence."""
    return " ".join(value.split()).casefold()


def _redacted_values(sheets, config) -> dict[str, dict[str, str]]:
    """Normalized value -> {column: original spelling} for every column
    being redacted, across every sheet."""
    values: dict[str, dict[str, str]] = {}
    for sheet in sheets:
        for column, action in config.get(sheet.name, {}).items():
            if action == "drop" or column not in sheet.headers:
                continue
            index = sheet.headers.index(column)
            for row in sheet.rows:
                cell = row[index].strip()
                if cell:
                    values.setdefault(_key(cell), {}).setdefault(column, cell)
    return values


def find_leaks(sheets, config: dict[str, dict[str, str]]) -> list[Leak]:
    tracked = _redacted_values(sheets, config)
    if not tracked:
        return []
    quotable = {v for v in tracked if len(v) >= MIN_SUBSTRING_LENGTH}

    leaks: list[Leak] = []
    for sheet in sheets:
        actions = config.get(sheet.name, {})
        kept = [h for h in sheet.headers if h not in actions]
        for kept_column in kept:
            index = sheet.headers.index(kept_column)
            found = _scan_column(sheet, index, tracked, quotable)
            for redacted_column, (count, samples) in found.items():
                leaks.append(
                    Leak(
                        sheet=sheet.name,
                        redacted_column=redacted_column,
                        kept_column=kept_column,
                        count=count,
                        samples=samples,
                    )
                )
    return leaks


def _windows(cell: str):
    """Word-aligned slices of a sentence, so a quoted value is found with a
    lookup per slice instead of a search per tracked value."""
    words = cell.split()
    for start in range(len(words)):
        for length in range(1, min(MAX_VALUE_WORDS, len(words) - start) + 1):
            window = " ".join(words[start : start + length]).strip(_EDGE_PUNCTUATION)
            if len(window) < MIN_SUBSTRING_LENGTH:
                continue
            yield window
            # "Ida Wells's guardian" holds the value "Ida Wells"
            for possessive in ("'s", "’s"):
                if window.endswith(possessive):
                    yield window[: -len(possessive)]


def _scan_column(sheet, index: int, tracked, quotable):
    hits: dict[str, tuple[int, list[str]]] = {}

    def record(value_key: str):
        for column, original in tracked[value_key].items():
            count, samples = hits.get(column, (0, []))
            if original not in samples and len(samples) < MAX_SAMPLES:
                samples = samples + [original]
            hits[column] = (count + 1, samples)

    for row_number, row in enumerate(sheet.rows):
        cell = row[index].strip()
        if not cell:
            continue
        key = _key(cell)
        if key in tracked:
            record(key)
            continue
        if quotable and row_number < MAX_SUBSTRING_ROWS:
            # One sentence can quote values from several redacted columns;
            # stopping at the first match hid the rest.
            seen: set[str] = set()
            for window in _windows(key):
                if window in quotable and window not in seen:
                    seen.add(window)
                    record(window)
    return hits


def find_weak_columns(sheets, config: dict[str, dict[str, str]]) -> list[str]:
    """Columns whose possible replacements are too few to hide anyone.

    Counted per replacement *type*, not per column: every column of a type
    draws from the same pool of fake values, so two 200-name columns crowd
    the list of first names exactly as much as one 400-name column. Judging
    each column alone let an ordinary two-column roster exhaust the pool
    while both columns sat under the threshold.
    """
    from app.engine.fakers import CROWDED_FRACTION, estimate_pool, normalize_value

    values_by_type: dict[str, set[str]] = {}
    columns_by_type: dict[str, list[str]] = {}
    for sheet in sheets:
        for column, action in config.get(sheet.name, {}).items():
            if action == "drop" or column not in sheet.headers:
                continue
            index = sheet.headers.index(column)
            values = values_by_type.setdefault(action, set())
            for row in sheet.rows:
                cell = normalize_value(row[index])
                if cell:
                    values.add(cell)
            names = columns_by_type.setdefault(action, [])
            if column not in names:
                names.append(column)

    weak: list[str] = []
    for col_type, values in values_by_type.items():
        if not values:
            continue
        if len(values) >= estimate_pool(col_type, values) * CROWDED_FRACTION:
            for column in columns_by_type[col_type]:
                if column not in weak:
                    weak.append(column)
    return weak
