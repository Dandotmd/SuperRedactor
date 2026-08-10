"""Direct tests for heading detection.

Guessing "heading" when the row is really a record is the one mistake that
puts a real person in a file labelled "redacted", because heading cells are
never replaced and the leak check only looks at rows. These test the
decision in isolation, at the level the rules are written.
"""

from app.engine.headings import (
    has_header,
    is_unambiguous_value,
    names_a_column,
    skeleton,
)


# ---- the label test --------------------------------------------------------

def test_a_word_that_names_a_column():
    for label in ("Name", "Client Name", "Date of Birth", "Emergency Contact",
                  "Total", "Amount Due", "Notes", "Student"):
        assert names_a_column(label), label


def test_labels_in_other_languages():
    for label in ("Nombre", "Apellidos", "Correo", "Fecha de Nacimiento",
                  "Prénom", "Adresse", "Vorname", "Nachname", "Betrag",
                  "Sobrenome", "Telefone"):
        assert names_a_column(label), label


def test_a_value_that_merely_contains_a_label_word_is_not_a_label():
    # 'school' is a heading word; this is an address
    assert not names_a_column("ada@school.edu")
    # a label carries no number
    assert not names_a_column("Grade 5")
    assert not names_a_column("FY2023")
    # nor is it a sentence
    assert not names_a_column(
        "Notes taken during the meeting with the guardian about the plan"
    )


def test_ordinary_data_is_not_a_label():
    for value in ("Ada Lovelace", "Boston", "Approved", "H0AK00105",
                  "(555) 555-1000", "-$40.00"):
        assert not names_a_column(value), value


# ---- shapes that settle it outright ---------------------------------------

def test_shapes_no_one_names_a_column_after():
    for value in ("ada@school.edu", "111-22-3333", "(555) 555-1000",
                  "2024-03-12", "3/12/2024", "Mar 1, 2024", "123456"):
        assert is_unambiguous_value(value), value


def test_ordinary_headings_are_not_those_shapes():
    for value in ("Name", "Score", "FY2023", "ICD-10-CM", "2023"):
        assert not is_unambiguous_value(value), value


# ---- the skeleton ---------------------------------------------------------

def test_skeleton_keeps_digit_length_and_punctuation():
    assert skeleton("(555) 555-1000") == "(999) 999-9999"
    assert skeleton("AB-100") == "a-999"
    assert skeleton("Mar 1, 2024") == "a 9, 9999"
    assert skeleton("2023") == "9999"
    assert skeleton("88") == "99"


def test_skeleton_treats_any_script_as_letters():
    assert skeleton("Иван") == "a"
    assert skeleton("А-100") == "a-999"


# ---- the decision ---------------------------------------------------------

HEADINGS = [
    (["Name", "Score"], [["Ada", "88"], ["Bo", "91"]]),
    (["Name", "2023", "2024"], [["Ada", "88", "91"], ["Bo", "75", "80"]]),
    (["FY2023", "FY2024"], [["100", "200"], ["300", "400"]]),
    (["ICD-10-CM", "DESCRIPTION"], [["A01", "Typhoid"], ["B02", "Zoster"]]),
    (["Region", "2020-2024", "Notes"], [["N", "10", "ok"], ["S", "20", "ok"]]),
    (["Nombre", "Edad"], [["Ada", "30"], ["Bo", "40"]]),
]

RECORDS = [
    (["1001", "Ada Lovelace"], [["1002", "Alan Turing"], ["1003", "Grace Hopper"]]),
    (["$1234", "Ada"], [["$2345", "Bo"], ["$3456", "Cy"]]),
    (["(555) 555-1000", "Ada"], [["(555) 555-1001", "Bo"]]),
    (["Mar 1, 2024", "Ada"], [["Mar 2, 2024", "Bo"]]),
    (["7", "Ada"], [["1234", "Bo"], ["5678", "Cy"]]),        # varying lengths
    (["2001", "Ada"], [["2002", "Bo"], ["2003", "Cy"]]),     # id that looks like a year
    (["Ada Lovelace", "Ms. Smith"], [["Alan Turing", "Mr. Jones"]]),
]


def test_heading_rows_are_recognised():
    for first, body in HEADINGS:
        assert has_header(first, body), first


def test_record_rows_are_recognised():
    for first, body in RECORDS:
        assert not has_header(first, body), first


def test_a_missing_value_marker_votes_neither_way():
    first = ["1001", "Ada Lovelace", "N/A"]
    body = [["1002", "Grace Hopper", "42"], ["1003", "Alan Turing", "37"]]
    assert not has_header(first, body)


def test_a_blank_first_row_is_a_heading():
    assert has_header(["", "  "], [["a", "b"]])


def test_one_row_alone():
    # says it is a record
    assert not has_header(["1001", "Ada", "ada@x.org"], [])
    # says nothing, so assume an export with headings and no rows
    assert has_header(["name", "email"], [])


def test_with_no_evidence_at_all_assume_a_record():
    """Every column heterogeneous, no label word, no telling shape. The
    safe direction is 'record' — a heading read as data costs the column
    names, a record read as a heading exposes somebody."""
    first = ["P1000X", "Mrs. Emma Smith MD"]
    body = [["P1", "Amy Kane"], ["", "David Miller"], ["Unknown", "Mathew Hinton"]]
    assert not has_header(first, body)


def test_the_decision_does_not_depend_on_dictionary_order():
    """A tie was once broken by set iteration order, so the same file
    parsed differently depending on the process hash seed."""
    first = ["7", "Ada"]
    body = [["1234", "Bo"], ["5678", "Cy"], ["9012", "Di"]]
    assert len({has_header(list(first), [list(r) for r in body]) for _ in range(50)}) == 1
