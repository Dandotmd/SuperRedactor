from app.engine.readers import Sheet
from app.engine.standardize import apply_template, make_template, match_columns


def students_sheet():
    return Sheet(
        name="Sheet1",
        headers=["student_id", "name", "email", "dob", "gpa"],
        rows=[
            ["S-1001", "Sarah Chen", "s@x.org", "2014-03-12", "3.8"],
            ["S-1002", "Bob Ray", "b@x.org", "2013-11-02", "3.1"],
            ["S-1003", "Maya Ortiz", "m@x.org", "2014-07-30", "3.9"],
        ],
    )


# ---- make_template --------------------------------------------------------

def test_template_captures_columns_and_guesses_types():
    template = make_template(students_sheet(), name="students")
    assert template["kind"] == "template"
    assert template["version"] == 1
    assert template["name"] == "students"
    cols = {c["name"]: c["type"] for c in template["columns"]}
    assert cols == {
        "student_id": "text",
        "name": "text",
        "email": "text",
        "dob": "date",
        "gpa": "number",
    }


# ---- match_columns --------------------------------------------------------

TEMPLATE_COLS = ["student_id", "name", "email", "dob"]


def test_matches_exact_and_case_insensitive_names():
    mapping = match_columns(TEMPLATE_COLS, ["Student ID", "Name", "EMAIL", "dob"])
    assert mapping == {
        "student_id": "Student ID",
        "name": "Name",
        "email": "EMAIL",
        "dob": "dob",
    }


def test_matches_synonyms():
    mapping = match_columns(TEMPLATE_COLS, ["ID", "Full Name", "E-mail Address", "Birth Date"])
    assert mapping["dob"] == "Birth Date"
    assert mapping["email"] == "E-mail Address"


def test_matches_fuzzy_typos():
    mapping = match_columns(["amount"], ["Amout"])
    assert mapping["amount"] == "Amout"


def test_matches_qualified_names_by_shared_tokens():
    # "Student Name" should land on "name", "ID" on "student_id"
    mapping = match_columns(["student_id", "name"], ["Student Name", "ID"])
    assert mapping == {"student_id": "ID", "name": "Student Name"}


def test_unmatched_template_column_is_none():
    mapping = match_columns(TEMPLATE_COLS, ["Student ID", "Homeroom"])
    assert mapping["student_id"] == "Student ID"
    assert mapping["email"] is None


def test_source_column_never_used_twice():
    mapping = match_columns(["name", "last_name"], ["Name"])
    used = [v for v in mapping.values() if v]
    assert len(used) == len(set(used)) == 1


# ---- apply_template -------------------------------------------------------

def system_b_sheet():
    # Same data, different system: renamed, reordered, extra column,
    # missing email, US dates, decorated numbers.
    return Sheet(
        name="Export",
        headers=["Student Name", "BirthDate", "ID", "Homeroom", "GPA"],
        rows=[
            ["Sarah Chen", "3/12/2014", "S-1001", "12B", "3.8"],
            ["Bob Ray", "11/2/2013", "S-1002", "9A", "3.1"],
        ],
    )


def template():
    return {
        "kind": "template",
        "version": 1,
        "name": "students",
        "columns": [
            {"name": "student_id", "type": "text"},
            {"name": "name", "type": "text"},
            {"name": "email", "type": "text"},
            {"name": "dob", "type": "date"},
            {"name": "gpa", "type": "number"},
        ],
    }


def full_mapping():
    return {
        "student_id": "ID",
        "name": "Student Name",
        "email": None,
        "dob": "BirthDate",
        "gpa": "GPA",
    }


def test_apply_renames_reorders_and_coerces():
    out, warnings = apply_template(system_b_sheet(), template(), full_mapping(), [])
    assert out.headers == ["student_id", "name", "email", "dob", "gpa"]
    assert out.rows[0] == ["S-1001", "Sarah Chen", "", "2014-03-12", "3.8"]
    assert out.rows[1] == ["S-1002", "Bob Ray", "", "2013-11-02", "3.1"]


def test_missing_column_produces_warning():
    _, warnings = apply_template(system_b_sheet(), template(), full_mapping(), [])
    assert any("email" in w for w in warnings)


def test_extras_dropped_by_default_kept_when_requested():
    out, _ = apply_template(system_b_sheet(), template(), full_mapping(), [])
    assert "Homeroom" not in out.headers
    out2, _ = apply_template(system_b_sheet(), template(), full_mapping(), ["Homeroom"])
    assert out2.headers[-1] == "Homeroom"
    assert out2.rows[0][-1] == "12B"


def test_uncoercible_cells_left_intact_and_warned():
    sheet = Sheet(
        name="S",
        headers=["When"],
        rows=[["3/12/2014"], ["unknown"], ["4/1/2014"]],
    )
    tpl = {
        "kind": "template", "version": 1, "name": "t",
        "columns": [{"name": "dob", "type": "date"}],
    }
    out, warnings = apply_template(sheet, tpl, {"dob": "When"}, [])
    assert [r[0] for r in out.rows] == ["2014-03-12", "unknown", "2014-04-01"]
    assert any("dob" in w and "1" in w for w in warnings)
