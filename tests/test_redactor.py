from app.engine.readers import Sheet
from app.engine.redactor import redact


def sample_sheets():
    return [
        Sheet(
            name="Students",
            headers=["id", "name", "score"],
            rows=[
                ["101", "Sarah Chen", "88"],
                ["102", "Bob Ray", "91"],
                ["103", "Sarah Chen", "75"],
            ],
        ),
        Sheet(
            name="Sessions",
            headers=["student_id", "note"],
            rows=[["101", "made progress"], ["999", "absent"]],
        ),
    ]


def config():
    return {
        "Students": {"id": "format_preserving", "name": "person_name"},
        "Sessions": {"student_id": "format_preserving"},
    }


def test_unredacted_columns_and_headers_unchanged():
    out, _ = redact(sample_sheets(), config())
    assert out[0].headers == ["id", "name", "score"]
    assert [r[2] for r in out[0].rows] == ["88", "91", "75"]
    assert [r[1] for r in out[1].rows] == ["made progress", "absent"]


def test_redacted_values_are_replaced():
    out, _ = redact(sample_sheets(), config())
    assert out[0].rows[0][1] != "Sarah Chen"
    assert out[0].rows[0][0] != "101"


def test_same_value_maps_to_same_fake_within_column():
    out, _ = redact(sample_sheets(), config())
    assert out[0].rows[0][1] == out[0].rows[2][1]  # both "Sarah Chen"


def test_same_value_same_type_consistent_across_sheets():
    out, _ = redact(sample_sheets(), config())
    # "101" appears in Students.id and Sessions.student_id, both format_preserving
    assert out[0].rows[0][0] == out[1].rows[0][0]


def test_distinct_values_get_distinct_fakes():
    out, _ = redact(sample_sheets(), config())
    fakes = {out[0].rows[0][0], out[0].rows[1][0], out[0].rows[2][0], out[1].rows[1][0]}
    assert len(fakes) == 4  # 101, 102, 103, 999


def test_empty_cells_stay_empty_and_unmapped():
    sheets = [Sheet(name="S", headers=["name"], rows=[[""], ["Sarah"]])]
    out, mapping = redact(sheets, {"S": {"name": "person_name"}})
    assert out[0].rows[0][0] == ""
    assert "" not in mapping["S"]["name"]


def test_drop_column_removes_it():
    sheets = [Sheet(name="S", headers=["ssn", "score"], rows=[["123-45-6789", "9"]])]
    out, mapping = redact(sheets, {"S": {"ssn": "drop"}})
    assert out[0].headers == ["score"]
    assert out[0].rows == [["9"]]
    assert "ssn" not in mapping.get("S", {})


def test_mapping_records_real_to_fake():
    out, mapping = redact(sample_sheets(), config())
    assert mapping["Students"]["name"]["Sarah Chen"] == out[0].rows[0][1]
    assert set(mapping["Students"]["id"]) == {"101", "102", "103"}


def test_large_file_redacts_in_reasonable_time():
    import time

    rows = [[f"2020-{(i % 12) + 1:02d}-01", str(i)] for i in range(20_000)]
    sheets = [Sheet(name="S", headers=["date", "score"], rows=rows)]
    start = time.monotonic()
    redact(sheets, {"S": {"date": "date"}})
    assert time.monotonic() - start < 3.0


def test_unknown_column_in_config_raises():
    import pytest

    with pytest.raises(ValueError, match="No such column"):
        redact(sample_sheets(), {"Students": {"nope": "person_name"}})
