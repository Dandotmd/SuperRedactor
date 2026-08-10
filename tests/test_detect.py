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


def test_non_pii_headers_get_no_suggestion():
    assert suggest_type("Score") is None
    assert suggest_type("Status") is None
    assert suggest_type("Notes") is None


def test_filename_does_not_crash_on_odd_headers():
    assert suggest_type("") is None
    assert suggest_type("   ") is None
