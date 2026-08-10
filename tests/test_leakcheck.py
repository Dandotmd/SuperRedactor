from app.engine.leakcheck import find_leaks
from app.engine.readers import Sheet


def test_exact_value_kept_in_another_column_is_reported():
    sheets = [
        Sheet(
            name="S",
            headers=["name", "emergency_contact", "score"],
            rows=[
                ["Sarah Chen", "Sarah Chen", "88"],
                ["Bob Ray", "Ann Ray", "91"],
            ],
        )
    ]
    leaks = find_leaks(sheets, {"S": {"name": "person_name"}})
    assert len(leaks) == 1
    assert leaks[0].kept_column == "emergency_contact"
    assert leaks[0].redacted_column == "name"
    assert leaks[0].count == 1
    assert "Sarah Chen" in leaks[0].samples


def test_value_inside_a_sentence_is_reported():
    sheets = [
        Sheet(
            name="S",
            headers=["name", "notes"],
            rows=[
                ["Sarah Chen", "Spoke with Sarah Chen about the plan"],
                ["Bob Ray", "No contact"],
            ],
        )
    ]
    leaks = find_leaks(sheets, {"S": {"name": "person_name"}})
    assert len(leaks) == 1
    assert leaks[0].kept_column == "notes"


def test_no_leak_when_nothing_repeats():
    sheets = [
        Sheet(
            name="S",
            headers=["name", "score"],
            rows=[["Sarah Chen", "88"], ["Bob Ray", "91"]],
        )
    ]
    assert find_leaks(sheets, {"S": {"name": "person_name"}}) == []


def test_dropped_columns_are_not_reported():
    sheets = [
        Sheet(
            name="S",
            headers=["name", "copy"],
            rows=[["Sarah Chen", "Sarah Chen"]],
        )
    ]
    leaks = find_leaks(sheets, {"S": {"name": "person_name", "copy": "drop"}})
    assert leaks == []


def test_other_redacted_columns_are_not_reported():
    sheets = [
        Sheet(
            name="S",
            headers=["name", "copy"],
            rows=[["Sarah Chen", "Sarah Chen"]],
        )
    ]
    leaks = find_leaks(
        sheets, {"S": {"name": "person_name", "copy": "person_name"}}
    )
    assert leaks == []


def test_short_values_do_not_trigger_substring_noise():
    # A 2-character ID would otherwise "appear" inside unrelated words
    sheets = [
        Sheet(
            name="S",
            headers=["code", "notes"],
            rows=[["AB", "Fabricated report"], ["CD", "nothing"]],
        )
    ]
    assert find_leaks(sheets, {"S": {"code": "format_preserving"}}) == []


def test_exact_match_still_reported_for_short_values():
    sheets = [
        Sheet(
            name="S",
            headers=["code", "backup_code"],
            rows=[["AB", "AB"], ["CD", "ZZ"]],
        )
    ]
    leaks = find_leaks(sheets, {"S": {"code": "format_preserving"}})
    assert len(leaks) == 1 and leaks[0].count == 1


def test_large_file_completes_quickly():
    import time

    rows = [[f"Person {i}", f"note {i}", "x"] for i in range(20_000)]
    rows[5] = ["Person 5", "call Person 5 back", "x"]
    sheets = [Sheet(name="S", headers=["name", "notes", "z"], rows=rows)]
    start = time.monotonic()
    leaks = find_leaks(sheets, {"S": {"name": "person_name"}})
    assert time.monotonic() - start < 5.0
    assert leaks and leaks[0].kept_column == "notes"
