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


def test_value_redacted_on_one_sheet_but_kept_on_another_is_reported():
    sheets = [
        Sheet(name="Roster", headers=["Student"], rows=[["Maria Lopez"], ["Devon Pryce"]]),
        Sheet(
            name="Services",
            headers=["Student", "Minutes"],
            rows=[["Maria Lopez", "60"], ["Devon Pryce", "30"]],
        ),
    ]
    leaks = find_leaks(sheets, {"Roster": {"Student": "person_name"}})
    assert leaks, "the name is still in the clear on the Services sheet"
    assert leaks[0].sheet == "Services"


def test_case_variants_are_reported():
    sheets = [
        Sheet(
            name="S",
            headers=["Student", "Notes"],
            rows=[
                ["Maria Lopez", "PARENT CONFERENCE WITH MARIA LOPEZ"],
                ["Devon Pryce", "IEP MEETING - DEVON PRYCE ABSENT"],
                ["Aisha Khan", "AISHA KHAN REFERRED TO COUNSELOR"],
            ],
        )
    ]
    leaks = find_leaks(sheets, {"S": {"Student": "person_name"}})
    assert leaks and leaks[0].count == 3, "all three shout-cased names must count"


def test_possessive_forms_are_reported():
    sheets = [
        Sheet(
            name="S",
            headers=["Student", "Notes"],
            rows=[
                ["Ida Wells", "Ida Wells's guardian called"],
                ["Bo Diddley", "nothing"],
                ["Cy Young", "nothing"],
            ],
        )
    ]
    assert find_leaks(sheets, {"S": {"Student": "person_name"}})


def test_exact_matches_are_found_beyond_the_first_20000_values():
    rows = [[f"Student {i}", ""] for i in range(20_005)]
    for i in (20_002, 20_003, 20_004):
        rows[i][1] = f"Student {i}"
    sheets = [Sheet(name="S", headers=["Student", "Guardian"], rows=rows)]
    leaks = find_leaks(sheets, {"S": {"Student": "person_name"}})
    assert leaks and leaks[0].count == 3


def test_two_redacted_columns_quoted_in_one_cell_are_both_reported():
    sheets = [
        Sheet(
            name="S",
            headers=["Student", "Guardian", "Notes"],
            rows=[
                ["Ida Wells", "Marcus Grey", "Ida Wells with Marcus Grey"],
                ["Bo Diddley", "Cleo Rand", "Bo Diddley with Cleo Rand"],
                ["Cy Young", "Ada Ray", "nothing"],
            ],
        )
    ]
    leaks = find_leaks(
        sheets, {"S": {"Student": "person_name", "Guardian": "person_name"}}
    )
    reported = {leak.redacted_column for leak in leaks}
    assert reported == {"Student", "Guardian"}, reported


def test_odd_internal_spacing_in_the_real_value_still_matches():
    sheets = [
        Sheet(
            name="S",
            headers=["Student", "Notes"],
            rows=[
                ["Ida  Wells", "spoke to Ida Wells"],
                ["Bo Diddley", "nothing"],
                ["Cy Young", "nothing"],
            ],
        )
    ]
    assert find_leaks(sheets, {"S": {"Student": "person_name"}})


def test_large_file_completes_quickly():
    import time

    rows = [[f"Person {i}", f"note {i}", "x"] for i in range(20_000)]
    rows[5] = ["Person 5", "call Person 5 back", "x"]
    sheets = [Sheet(name="S", headers=["name", "notes", "z"], rows=rows)]
    start = time.monotonic()
    leaks = find_leaks(sheets, {"S": {"name": "person_name"}})
    assert time.monotonic() - start < 5.0
    assert leaks and leaks[0].kept_column == "notes"
