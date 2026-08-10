"""Randomized property test for the promise the whole tool rests on:

    a column marked for replacement never emits one of its real values,
    and if that becomes impossible, the user is warned before downloading.

Every specific leak found so far had its own regression test. This covers
the shapes nobody thought to try — random column types, multi-sheet files,
drop-and-replace combinations, duplicate and near-duplicate values.
"""

import random

from faker import Faker

from app.engine.fakers import normalize_value
from app.engine.leakcheck import find_weak_columns
from app.engine.readers import Sheet
from app.engine.redactor import redact

FAKER = Faker()

VALUE_MAKERS = {
    "person_name": lambda f: f.name(),
    "first_name": lambda f: f.first_name(),
    "last_name": lambda f: f.last_name(),
    "email": lambda f: f.email(),
    "phone": lambda f: f.numerify("(###) ###-####"),
    "ssn": lambda f: f.ssn(),
    "address": lambda f: f.street_address(),
    "city": lambda f: f.city(),
    "date": lambda f: f.date(),
    "number": lambda f: str(f.random_int(1, 99999)),
    "format_preserving": lambda f: f.bothify("??-####"),
    "custom_word": lambda f: f.word(),
}


def _random_sheet(rng: random.Random, name: str) -> tuple[Sheet, dict[str, str]]:
    types = rng.sample(sorted(VALUE_MAKERS), rng.randint(1, 4))
    headers = [f"col_{i}_{t}" for i, t in enumerate(types)]
    rows = []
    for _ in range(rng.randint(1, 40)):
        row = []
        for t in types:
            value = VALUE_MAKERS[t](FAKER)
            if rng.random() < 0.15:  # empties, padding and case variants
                value = rng.choice(["", " ", value.upper(), f"  {value} "])
            row.append(value)
        rows.append(row)
    # repeat some rows so duplicate values are exercised
    for _ in range(rng.randint(0, 5)):
        if rows:
            rows.append(list(rng.choice(rows)))

    config = {}
    for header, col_type in zip(headers, types):
        choice = rng.random()
        if choice < 0.6:
            config[header] = col_type
        elif choice < 0.7:
            config[header] = "drop"
    return Sheet(name=name, headers=headers, rows=rows), config


def test_no_real_value_survives_random_redactions():
    rng = random.Random(20260810)
    for case in range(300):
        sheets = []
        config = {}
        for s in range(rng.randint(1, 3)):
            sheet, columns = _random_sheet(rng, f"Sheet{s}")
            sheets.append(sheet)
            if columns:
                config[sheet.name] = columns
        if not config:
            continue

        redacted, mapping = redact(sheets, config)
        warned = set(find_weak_columns(sheets, config))

        for original, out in zip(sheets, redacted):
            actions = config.get(original.name, {})
            for column, action in actions.items():
                if action == "drop" or column in warned:
                    continue
                index = original.headers.index(column)
                real = {r[index].strip() for r in original.rows if r[index].strip()}
                out_index = out.headers.index(column)
                produced = {r[out_index].strip() for r in out.rows if r[out_index].strip()}
                assert not (produced & real), (
                    f"case {case}: {column} emitted real values "
                    f"{sorted(produced & real)[:3]} with no warning"
                )


def test_one_fake_never_means_two_people_in_random_files():
    rng = random.Random(4242)
    for case in range(200):
        sheets = []
        config = {}
        for s in range(rng.randint(1, 3)):
            sheet, columns = _random_sheet(rng, f"Sheet{s}")
            sheets.append(sheet)
            if columns:
                config[sheet.name] = columns
        if not config:
            continue

        _, mapping = redact(sheets, config)
        # Several spellings of one value legitimately share a fake; two
        # genuinely different values must never.
        fakes: dict[str, str] = {}
        for columns in mapping.values():
            for pairs in columns.values():
                for real, fake in pairs.items():
                    key = normalize_value(real)
                    assert fakes.setdefault(fake, key) == key, (
                        f"case {case}: fake {fake!r} stands for both "
                        f"{fakes[fake]!r} and {key!r}"
                    )


def test_values_from_dropped_columns_are_never_handed_out_as_fakes():
    """A removed column's values are data the user chose to delete, so no
    replacement anywhere may come back as one of them.

    Compared cell by cell: a fake surname of "Stevens" containing the
    removed first name "Steven" is a coincidence of spelling, not a
    reappearance of the value.
    """
    from app.engine.fakers import normalize_value

    rng = random.Random(99)
    for case in range(100):
        sheet, config = _random_sheet(rng, "S")
        dropped = [c for c, a in config.items() if a == "drop"]
        if not dropped:
            continue
        redacted, mapping = redact([sheet], {"S": config})

        removed = set()
        for column in dropped:
            index = sheet.headers.index(column)
            removed |= {
                normalize_value(r[index]) for r in sheet.rows if r[index].strip()
            }
        # Only values the tool invented count. A removed value that also sits
        # in a column the user kept is still on screen by their choice.
        invented = {
            normalize_value(fake)
            for columns in mapping.values()
            for pairs in columns.values()
            for fake in pairs.values()
        }
        assert not (invented & removed), (
            f"case {case}: removed values {sorted(invented & removed)[:3]} "
            f"came back as replacements"
        )
        assert all(c not in redacted[0].headers for c in dropped)
