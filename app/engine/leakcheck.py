"""Warn when a value being redacted in one column survives in a column the
user chose to keep.

Column-level redaction can't see that the name in 'name' is repeated in
'emergency_contact' or quoted inside a 'notes' sentence. Someone who ticks
the suggested columns and downloads would ship the very data they meant to
hide, so this check runs before the download and says so plainly.
"""

import re
from dataclasses import dataclass, field

# Exact-cell matching is a set lookup and runs over every row, so the
# "same value in two columns" case is always caught in full.
#
# Finding a value quoted inside a sentence needs a substring search, which
# costs far more, so it runs against a bounded sample. It is a bonus signal
# on top of the exact check, not the guarantee.
MAX_TRACKED_VALUES = 20_000
MAX_SUBSTRING_ROWS = 50_000
MIN_SUBSTRING_LENGTH = 4
MAX_VALUE_WORDS = 5
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
            quotable = {v for v in values if len(v) >= MIN_SUBSTRING_LENGTH}
            for kept_column in kept:
                leak = _scan_column(sheet, idx[kept_column], values, quotable)
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


_EDGE_PUNCTUATION = " \t.,;:!?()[]{}\"'"


def _quoted_value(cell: str, quotable: set[str]) -> str | None:
    """Find a tracked value quoted inside a sentence.

    Looks up word-aligned windows of the cell in the value set rather than
    searching for each value in the cell: one hash lookup per window keeps
    this linear in the text, so no cap on the number of values is needed
    and nothing is missed on a big file.
    """
    words = cell.split()
    if len(words) < 2:
        return None
    for start in range(len(words)):
        for length in range(1, min(MAX_VALUE_WORDS, len(words) - start) + 1):
            window = " ".join(words[start : start + length]).strip(_EDGE_PUNCTUATION)
            if len(window) >= MIN_SUBSTRING_LENGTH and window in quotable:
                return window
    return None


def _scan_column(sheet, index: int, values: set[str], quotable: set[str]):
    count = 0
    samples: list[str] = []
    for row_number, row in enumerate(sheet.rows):
        cell = row[index].strip()
        if not cell:
            continue
        hit = None
        if cell in values:
            hit = cell
        elif quotable and row_number < MAX_SUBSTRING_ROWS:
            hit = _quoted_value(cell, quotable)
        if hit is not None:
            count += 1
            if hit not in samples and len(samples) < MAX_SAMPLES:
                samples.append(hit)
    return (count, samples) if count else None
