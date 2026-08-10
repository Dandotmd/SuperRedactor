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


def test_redaction_warns_when_a_column_is_too_small_to_hide_anything():
    from app.engine.readers import Sheet

    # 26 single letters: any single-letter fake is somebody's real grade
    rows = [[chr(ord("A") + i)] for i in range(26)]
    sheets = [Sheet(name="S", headers=["grade"], rows=rows)]
    _, _, warnings = redact(sheets, {"S": {"grade": "format_preserving"}}, report=True)
    assert any("grade" in w for w in warnings)
