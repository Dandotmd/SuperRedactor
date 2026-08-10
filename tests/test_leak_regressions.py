"""Regressions for ways real data reached 'redacted' output.

Every test here corresponds to a confirmed leak found by adversarial
testing. They assert on the property that matters — no real value survives
— rather than on the mechanism, so a future refactor can't quietly
reintroduce the leak.
"""

from app.engine.cleaners import analyze, apply_fixes
from app.engine.readers import read_file
from app.engine.redactor import redact
from app.engine.writers import write_csv


def all_output_text(sheets) -> str:
    return "\n".join(
        write_csv(s).decode() for s in sheets
    )


# ---- header row is data ---------------------------------------------------

def test_cleaning_keeps_a_short_header_row_as_the_header():
    # Trailing unnamed columns make the header row sparser than the data
    # rows; the header must still be recognised as the header.
    data = (
        b"Name,Email,,\n"
        b"Ada Lovelace,ada@school.edu,Math,A\n"
        b"Grace Hopper,grace@school.edu,CS,B\n"
        b"Alan Turing,alan@school.edu,Logic,A\n"
    )
    sheets = read_file("class.csv", data)
    cleaned = apply_fixes(sheets, {f.id for f in analyze(sheets)})
    assert len(cleaned[0].rows) == 3
    assert "Ada Lovelace" not in cleaned[0].headers


def test_headerless_roster_keeps_every_person_as_a_data_row():
    data = (
        b"Ada Lovelace,ada@school.edu,111-22-3333\n"
        b"Grace Hopper,grace@school.edu,222-33-4444\n"
        b"Alan Turing,alan@school.edu,333-44-5555\n"
    )
    sheets = read_file("roster.csv", data)
    assert len(sheets[0].rows) == 3
    assert "Ada Lovelace" not in sheets[0].headers


def test_no_real_value_survives_redaction_of_a_headerless_roster():
    data = (
        b"Ada Lovelace,ada@school.edu,111-22-3333\n"
        b"Grace Hopper,grace@school.edu,222-33-4444\n"
    )
    sheets = read_file("roster.csv", data)
    config = {
        sheets[0].name: {h: t for h, t in zip(sheets[0].headers, ["person_name", "email", "ssn"])}
    }
    redacted, _ = redact(sheets, config)
    output = all_output_text(redacted)
    for real in ("Ada Lovelace", "ada@school.edu", "111-22-3333", "Grace Hopper"):
        assert real not in output


# ---- fake values colliding with real ones ---------------------------------

def test_a_fake_name_is_never_another_persons_real_name():
    names = [
        "Brian", "Christopher", "Michael", "Jennifer", "Patricia", "Linda",
        "Barbara", "Susan", "Jessica", "Sarah", "Karen", "Nancy", "Betty",
        "Dorothy", "Sandra", "Ashley", "Kimberly", "Donna", "Emily", "Carol",
    ]
    from app.engine.readers import Sheet

    sheets = [Sheet(name="S", headers=["first"], rows=[[n] for n in names])]
    for _ in range(5):
        redacted, _ = redact(sheets, {"S": {"first": "first_name"}})
        produced = {r[0] for r in redacted[0].rows}
        assert not (produced & set(names)), produced & set(names)


def test_one_fake_never_stands_for_two_different_real_values():
    from app.engine.readers import Sheet

    rows = [[f"First{i}", f"Last{i}"] for i in range(60)]
    sheets = [Sheet(name="S", headers=["first", "last"], rows=rows)]
    for _ in range(5):
        _, mapping = redact(
            sheets, {"S": {"first": "first_name", "last": "last_name"}}
        )
        pairs = []
        for column in mapping["S"].values():
            pairs.extend(column.items())
        fakes = [fake for _, fake in pairs]
        assert len(fakes) == len(set(fakes)), "a fake was reused for two real values"


def test_reused_real_names_are_always_warned_about_first():
    """The worst case: the real names come from the same pool the generator
    draws from, so avoiding them all is impossible past a certain size. The
    tool may reuse a value — it may never do so silently."""
    from faker import Faker

    from app.engine.leakcheck import find_weak_columns
    from app.engine.readers import Sheet

    faker = Faker()
    for count in (200, 300, 400, 600):
        pool: set[str] = set()
        while len(pool) < count:
            pool.add(faker.first_name())
        names = sorted(pool)
        sheets = [Sheet(name="S", headers=["first"], rows=[[n] for n in names])]
        config = {"S": {"first": "first_name"}}

        # Same seed for both, so the check describes this exact run
        redacted, _ = redact(sheets, config, seed=7)
        reused = {r[0] for r in redacted[0].rows} & set(names)
        if reused:
            assert find_weak_columns(sheets, config, seed=7), (
                f"{len(reused)} of {count} real names reused with no warning"
            )


def _crowding_bypass_case(second_action: str, second_type: str):
    """A column the generator must avoid, that the prediction didn't count:
    either a column marked for removal, or a second type drawing on the
    same kind of value."""
    from faker import Faker

    from app.engine.readers import Sheet

    faker = Faker()
    pool: set[str] = set()
    while len(pool) < 650:
        pool.add(faker.first_name())
    names = sorted(pool)

    rows = [[names[i], names[i + 200]] for i in range(200)]
    sheets = [Sheet(name="S", headers=["Given", "Other"], rows=rows)]
    config = {"S": {"Given": "first_name", "Other": second_action or second_type}}
    return sheets, config


def test_a_removed_column_still_counts_against_the_pool():
    """The generator must avoid values from removed columns too, so they
    crowd the pool exactly as much as replaced ones."""
    from app.engine.leakcheck import find_weak_columns

    sheets, config = _crowding_bypass_case("drop", "")
    redacted, _ = redact(sheets, config, seed=11)
    real = {c.strip() for row in sheets[0].rows for c in row if c.strip()}
    produced = {c.strip() for row in redacted[0].rows for c in row if c.strip()}
    if produced & real:
        assert find_weak_columns(sheets, config, seed=11), (
            f"{len(produced & real)} real values reused with no warning"
        )


def test_a_second_type_drawing_on_the_same_words_counts_too():
    from app.engine.leakcheck import find_weak_columns

    sheets, config = _crowding_bypass_case("", "person_name")
    redacted, _ = redact(sheets, config, seed=13)
    given = {r[0].strip() for r in sheets[0].rows if r[0].strip()}
    produced = {r[0].strip() for r in redacted[0].rows if r[0].strip()}
    if produced & given:
        assert find_weak_columns(sheets, config, seed=13), (
            f"{len(produced & given)} real names reused with no warning"
        )


def test_two_columns_of_one_type_share_the_pool_and_are_warned_together():
    """The generator draws every column of a type from one pool, so two
    200-name columns crowd it exactly as much as one 400-name column."""
    from faker import Faker

    from app.engine.leakcheck import find_weak_columns
    from app.engine.readers import Sheet

    faker = Faker()
    pool: set[str] = set()
    while len(pool) < 400:
        pool.add(faker.first_name())
    names = sorted(pool)

    sheets = [
        Sheet(
            name="S",
            headers=["Student First", "Guardian First"],
            rows=[[names[i], names[i + 200]] for i in range(200)],
        )
    ]
    config = {"S": {"Student First": "first_name", "Guardian First": "first_name"}}

    warned = find_weak_columns(sheets, config)
    assert {w.column for w in warned} == {"Student First", "Guardian First"}, warned


def test_columns_of_one_type_spread_over_sheets_are_warned():
    from faker import Faker

    from app.engine.leakcheck import find_weak_columns
    from app.engine.readers import Sheet

    faker = Faker()
    pool: set[str] = set()
    while len(pool) < 500:
        pool.add(faker.first_name())
    names = sorted(pool)

    sheets = [
        Sheet(name="A", headers=["First"], rows=[[n] for n in names[:250]]),
        Sheet(name="B", headers=["First"], rows=[[n] for n in names[250:]]),
    ]
    config = {"A": {"First": "first_name"}, "B": {"First": "first_name"}}
    assert find_weak_columns(sheets, config)


def test_no_real_first_name_is_reused_at_school_roster_size():
    """400 distinct first names is an ordinary school. The generator's pool
    is smaller than that, so this must either avoid every real value or say
    out loud that it cannot."""
    from app.engine.leakcheck import find_weak_columns
    from app.engine.readers import Sheet

    names = [f"RealName{i}" for i in range(400)]
    sheets = [Sheet(name="S", headers=["first"], rows=[[n] for n in names])]
    config = {"S": {"first": "first_name"}}

    redacted, _ = redact(sheets, config)
    produced = {r[0] for r in redacted[0].rows}
    reused = produced & set(names)

    warned = find_weak_columns(sheets, config)
    assert not reused or warned, (
        f"{len(reused)} real names reused as someone else's fake, with no warning"
    )


def test_no_false_alarm_on_a_normal_sized_column():
    from app.engine.leakcheck import find_weak_columns
    from app.engine.readers import Sheet

    rows = [[f"RealName{i}"] for i in range(60)]
    sheets = [Sheet(name="S", headers=["first"], rows=rows)]
    assert find_weak_columns(sheets, {"S": {"first": "first_name"}}) == []


def test_no_false_alarm_when_the_values_are_not_in_the_generators_own_list():
    """Names the generator has never heard of leave its pool untouched, so
    there is nothing to warn about."""
    from app.engine.leakcheck import find_weak_columns
    from app.engine.readers import Sheet

    rows = [[f"Pseudonym{i}"] for i in range(300)]
    sheets = [Sheet(name="S", headers=["first"], rows=rows)]
    assert find_weak_columns(sheets, {"S": {"first": "first_name"}}) == []


def test_weak_columns_name_their_sheet():
    from app.engine.leakcheck import find_weak_columns
    from app.engine.readers import Sheet

    rows = [[chr(ord("A") + i)] for i in range(26)]
    sheets = [
        Sheet(name="Marks", headers=["Grade"], rows=rows),
        Sheet(name="Other", headers=["Grade"], rows=[["AA-11111"], ["BB-22222"]]),
    ]
    weak = find_weak_columns(
        sheets,
        {
            "Marks": {"Grade": "format_preserving"},
            "Other": {"Grade": "format_preserving"},
        },
    )
    assert [(w.sheet, w.column) for w in weak] == [("Marks", "Grade")]


def test_redaction_warns_when_a_column_is_too_small_to_hide_anything():
    from app.engine.readers import Sheet

    # 26 single letters: any single-letter fake is somebody's real grade
    rows = [[chr(ord("A") + i)] for i in range(26)]
    sheets = [Sheet(name="S", headers=["grade"], rows=rows)]
    _, _, weak = redact(sheets, {"S": {"grade": "format_preserving"}}, report=True)
    assert [w.column for w in weak] == ["grade"]
