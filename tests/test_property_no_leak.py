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
    # Types may repeat: every column of a type draws from one shared pool of
    # fakes, and only picking distinct types hid exactly that bug once.
    types = [rng.choice(sorted(VALUE_MAKERS)) for _ in range(rng.randint(1, 4))]
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


def test_a_headerless_file_never_loses_its_first_record_to_the_heading_row():
    """Heading cells are never redacted, so a record mistaken for the
    headings ships in the clear. Generated across the column shapes real
    exports open with — ids, money, dates, codes, names — because each
    time this broke it was a shape nobody had tried."""
    from app.engine.readers import read_file
    from app.engine.writers import write_csv

    rng = random.Random(602214)
    first_column = [
        lambda i: f"{100 + i}",               # 3-digit id
        lambda i: f"{1000 + i}",              # 4-digit id
        lambda i: f"{2000 + i}",              # id that looks like a year
        lambda i: f"${1000 + i}",             # money
        lambda i: f"-${100 + i}.00",          # negative money
        lambda i: f"({100 + i}.00)",          # accounting money
        lambda i: f"{10 + i}.50",             # decimal
        lambda i: f"{40 + i}%",               # percentage
        lambda i: f"{40 + i}.5%",
        lambda i: f"(555) 555-{1000 + i}",    # phone, as the tool's own faker writes it
        lambda i: f"555-555-{1000 + i}",
        lambda i: f"H0AK{i:05d}",             # long record code
        lambda i: f"AB-{100 + i}",            # short code
        lambda i: f"P{1000 + i}X",
        lambda i: FAKER.ssn(),
        lambda i: FAKER.email(),
        lambda i: f"2024-03-{(i % 28) + 1:02d}",
        lambda i: f"3/{(i % 28) + 1}/2024",
        lambda i: f"Mar {(i % 28) + 1}, 2024",       # text month
        lambda i: f"March {(i % 28) + 1}, 2024",
        lambda i: f"{(i % 28) + 1:02d}-Mar-2024",
    ]
    # A file of nothing but prose has no decidable signal at all — see
    # test_an_all_text_headerless_file_is_a_known_limitation.
    for case, make_first in enumerate(first_column):
        for width in (2, 4, 6):
            rows = [
                [make_first(i)]
                + [FAKER.name(), "Ms. Smith", f"Grade {i % 6}", "Approved", "x"][
                    : width - 1
                ]
                for i in range(6)
            ]
            sheet = Sheet(name="S", headers=[f"c{i}" for i in range(width)], rows=rows)
            data = write_csv(sheet).decode().split("\n", 1)[1].encode()

            parsed = read_file("roster.csv", data)[0]
            assert len(parsed.rows) == 6, (
                f"case {case} width {width}: record one became the heading "
                f"{parsed.headers}"
            )
            _ = rng


def test_an_all_text_headerless_file_is_a_known_limitation():
    """Named so nobody has to rediscover it.

    "Ada Lovelace,Ms. Smith" as a first record is indistinguishable from
    "Full Name,Teacher" as a heading — same words, same shape, no numbers
    or addresses to give it away. The tool reads it as a heading, so that
    record is not replaced. Anything with an id, a date, an email, an
    amount or a code anywhere in the row is decidable and is covered by
    the property test above; this is documented in the README's Limits.
    """
    from app.engine.readers import read_file

    data = (
        b"Ada Lovelace,Ms. Smith\n"
        b"Alan Turing,Mr. Jones\n"
        b"Grace Hopper,Ms. Smith\n"
    )
    sheet = read_file("roster.csv", data)[0]
    assert sheet.headers == ["Ada Lovelace", "Ms. Smith"]
    assert len(sheet.rows) == 2


def test_no_removed_value_is_ever_handed_back_as_a_replacement():
    """A value the user deleted must never reappear as another row's fake,
    whatever type either column is. Case matters here: identifiers compare
    case-sensitively, and protecting a removed value under only one of the
    two comparison forms let uppercase codes come straight back."""
    from app.engine.fakers import normalize_value

    rng = random.Random(31337)
    for case in range(200):
        removed_type = rng.choice(sorted(VALUE_MAKERS))
        kept_type = rng.choice(sorted(VALUE_MAKERS))
        values = [VALUE_MAKERS[removed_type](FAKER) for _ in range(rng.randint(5, 40))]
        rows = [[VALUE_MAKERS[kept_type](FAKER), v] for v in values]
        sheets = [Sheet(name="S", headers=["keep", "gone"], rows=rows)]
        config = {"S": {"keep": kept_type, "gone": "drop"}}

        redacted, _ = redact(sheets, config, seed=case)
        removed = {normalize_value(v) for v in values}
        produced = {
            normalize_value(cell)
            for row in redacted[0].rows
            for cell in row
            if cell.strip()
        }
        assert not (produced & removed), (
            f"case {case} ({removed_type} removed, {kept_type} kept): "
            f"{sorted(produced & removed)[:3]} came back"
        )


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


def test_columns_sharing_a_pool_are_warned_before_any_value_is_reused():
    """Spread one type over several columns and sheets until the pool is
    crowded. Reuse is allowed there — silence is not."""
    # The small pools are the ones a real roster crowds; larger ones would
    # only make the suite slow.
    rng = random.Random(1234)
    for col_type, pool_hint in [("first_name", 690), ("last_name", 1000)]:
        for columns in (2, 3, 4):
            # Half the pool: past the warning threshold, and far cheaper to
            # sample than approaching exhaustion.
            per_column = max(1, int(pool_hint * 0.5) // columns)
            values: set[str] = set()
            while len(values) < per_column * columns:
                values.add(VALUE_MAKERS[col_type](FAKER))
            ordered = sorted(values)

            headers = [f"col{i}" for i in range(columns)]
            rows = [
                [ordered[c * per_column + r] for c in range(columns)]
                for r in range(per_column)
            ]
            sheets = [Sheet(name="S", headers=headers, rows=rows)]
            config = {"S": {h: col_type for h in headers}}

            redacted, _ = redact(sheets, config)
            produced = {c.strip() for row in redacted[0].rows for c in row if c.strip()}
            reused = produced & set(ordered)
            if reused:
                assert find_weak_columns(sheets, config), (
                    f"{col_type} over {columns} columns: {len(reused)} real "
                    f"values reused with no warning"
                )
            _ = rng  # deterministic ordering only


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
