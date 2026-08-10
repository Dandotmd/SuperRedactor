from app.engine.detect import suggest_type


def test_name_headers():
    assert suggest_type("Name") == "person_name"
    assert suggest_type("Student Name") == "person_name"
    assert suggest_type("first_name") == "first_name"
    assert suggest_type("LastName") == "last_name"


def test_contact_headers():
    assert suggest_type("Email Address") == "email"
    assert suggest_type("phone_number") == "phone"
    assert suggest_type("Home Address") == "address"
    assert suggest_type("City") == "city"


def test_identifier_headers():
    assert suggest_type("SSN") == "ssn"
    assert suggest_type("Social Security Number") == "ssn"
    assert suggest_type("Student ID") == "format_preserving"
    assert suggest_type("MRN") == "format_preserving"


def test_date_headers():
    assert suggest_type("DOB") == "date"
    assert suggest_type("Birth Date") == "date"
    assert suggest_type("date_of_service") == "date"


def test_common_short_name_headers():
    for header in ("First", "Last", "FName", "LName", "Forename"):
        assert suggest_type(header) in ("first_name", "last_name"), header


def test_person_role_headers_are_treated_as_names():
    for header in ("Patient", "Student", "Guardian", "Employee", "Client",
                   "Parent", "Teacher", "Emergency Contact"):
        assert suggest_type(header) == "person_name", header


def test_cell_is_a_phone_column():
    assert suggest_type("Cell") == "phone"


def test_non_pii_headers_get_no_suggestion():
    assert suggest_type("Score") is None
    assert suggest_type("Status") is None
    assert suggest_type("Notes") is None


def test_filename_does_not_crash_on_odd_headers():
    assert suggest_type("") is None
    assert suggest_type("   ") is None
