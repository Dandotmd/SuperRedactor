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
    out = apply_template(system_b_sheet(), template(), full_mapping(), []).sheet
    assert out.headers == ["student_id", "name", "email", "dob", "gpa"]
    assert out.rows[0] == ["S-1001", "Sarah Chen", "", "2014-03-12", "3.8"]
    assert out.rows[1] == ["S-1002", "Bob Ray", "", "2013-11-02", "3.1"]


def test_missing_column_produces_warning():
    result = apply_template(system_b_sheet(), template(), full_mapping(), [])
    assert any("email" in w for w in result.warnings)


def test_extras_dropped_by_default_kept_when_requested():
    out = apply_template(system_b_sheet(), template(), full_mapping(), []).sheet
    assert "Homeroom" not in out.headers
    out2 = apply_template(system_b_sheet(), template(), full_mapping(), ["Homeroom"]).sheet
    assert out2.headers[-1] == "Homeroom"
    assert out2.rows[0][-1] == "12B"


# ---- value vocabularies ---------------------------------------------------

def categorical_sheet():
    return Sheet(
        name="S",
        headers=["name", "status"],
        rows=[
            ["Sarah", "active"],
            ["Bob", "inactive"],
            ["Maya", "active"],
            ["Tom", "active"],
            ["Ann", "inactive"],
        ],
    )


def test_template_captures_vocabulary_for_categorical_columns():
    template = make_template(categorical_sheet(), name="t")
    status = next(c for c in template["columns"] if c["name"] == "status")
    assert sorted(status["values"]) == ["active", "inactive"]


def test_template_skips_vocabulary_for_high_cardinality_columns():
    template = make_template(categorical_sheet(), name="t")
    name_col = next(c for c in template["columns"] if c["name"] == "name")
    assert "values" not in name_col


def vocab_template():
    return {
        "kind": "template", "version": 1, "name": "t",
        "columns": [
            {"name": "status", "type": "text", "values": ["active", "inactive"]},
        ],
    }


def test_case_and_whitespace_variants_map_to_canonical_value():
    sheet = Sheet(name="S", headers=["Status"], rows=[["ACTIVE"], [" Active "], ["In-Active"]])
    result = apply_template(sheet, vocab_template(), {"status": "Status"}, [])
    assert [r[0] for r in result.sheet.rows] == ["active", "active", "inactive"]


def test_unknown_values_are_left_alone_and_reported_for_mapping():
    sheet = Sheet(name="S", headers=["Status"], rows=[["active"], ["on leave"], ["on leave"]])
    result = apply_template(sheet, vocab_template(), {"status": "Status"}, [])
    assert [r[0] for r in result.sheet.rows] == ["active", "on leave", "on leave"]
    assert result.unmatched == {"status": ["on leave"]}
    assert any("status" in w and "on leave" in w for w in result.warnings)


def test_similar_but_distinct_values_are_never_fuzzy_merged():
    # "active"/"inactive" are textually similar; merging them would corrupt data
    sheet = Sheet(name="S", headers=["Status"], rows=[["activ"], ["inactiv"]])
    result = apply_template(sheet, vocab_template(), {"status": "Status"}, [])
    assert [r[0] for r in result.sheet.rows] == ["activ", "inactiv"]


def test_explicit_aliases_are_applied():
    template = vocab_template()
    template["columns"][0]["aliases"] = {"on leave": "inactive"}
    sheet = Sheet(name="S", headers=["Status"], rows=[["on leave"], ["ACTIVE"]])
    result = apply_template(sheet, template, {"status": "Status"}, [])
    assert [r[0] for r in result.sheet.rows] == ["inactive", "active"]
    assert result.unmatched == {}


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
    result = apply_template(sheet, tpl, {"dob": "When"}, [])
    assert [r[0] for r in result.sheet.rows] == ["2014-03-12", "unknown", "2014-04-01"]
    assert any("dob" in w and "1" in w for w in result.warnings)
