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

        redacted, _ = redact(sheets, config)
        reused = {r[0] for r in redacted[0].rows} & set(names)
        if reused:
            assert find_weak_columns(sheets, config), (
                f"{len(reused)} of {count} real names reused with no warning"
            )


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


def test_warning_fires_before_collisions_actually_start():
    from app.engine.leakcheck import find_weak_columns
    from app.engine.readers import Sheet

    for count in (350, 400, 500, 600):
        rows = [[f"RealName{i}"] for i in range(count)]
        sheets = [Sheet(name="S", headers=["first"], rows=rows)]
        assert find_weak_columns(sheets, {"S": {"first": "first_name"}}), (
            f"{count} distinct names should warn — the pool holds ~690"
        )


def test_no_false_alarm_on_a_normal_sized_column():
    from app.engine.leakcheck import find_weak_columns
    from app.engine.readers import Sheet

    rows = [[f"RealName{i}"] for i in range(60)]
    sheets = [Sheet(name="S", headers=["first"], rows=rows)]
    assert find_weak_columns(sheets, {"S": {"first": "first_name"}}) == []


def test_last_name_boundary_warns():
    from app.engine.leakcheck import find_weak_columns
    from app.engine.readers import Sheet

    rows = [[f"RealSurname{i}"] for i in range(500)]
    sheets = [Sheet(name="S", headers=["last"], rows=rows)]
    assert find_weak_columns(sheets, {"S": {"last": "last_name"}})


def test_redaction_warns_when_a_column_is_too_small_to_hide_anything():
    from app.engine.readers import Sheet

    # 26 single letters: any single-letter fake is somebody's real grade
    rows = [[chr(ord("A") + i)] for i in range(26)]
    sheets = [Sheet(name="S", headers=["grade"], rows=rows)]
    _, _, warnings = redact(sheets, {"S": {"grade": "format_preserving"}}, report=True)
    assert any("grade" in w for w in warnings)
