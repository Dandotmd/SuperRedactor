import re

from app.engine.fakers import FakeGenerator, REDACTION_TYPES


def test_all_declared_types_produce_values():
    for col_type in REDACTION_TYPES:
        gen = FakeGenerator(col_type)
        value = gen.next("Sample123")
        assert isinstance(value, str)
        assert value != ""


def test_person_name_differs_from_original():
    gen = FakeGenerator("person_name")
    assert gen.next("Sarah Chen") != "Sarah Chen"


def test_ssn_shape():
    gen = FakeGenerator("ssn")
    assert re.fullmatch(r"\d{3}-\d{2}-\d{4}", gen.next("123-45-6789"))


def test_email_shape():
    gen = FakeGenerator("email")
    assert "@" in gen.next("sarah@example.com")


def test_date_shape():
    gen = FakeGenerator("date")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", gen.next("2001-04-15"))


def test_format_preserving_keeps_pattern():
    gen = FakeGenerator("format_preserving")
    fake = gen.next("AB-1234x")
    assert re.fullmatch(r"[A-Z]{2}-\d{4}[a-z]", fake)
    assert fake != "AB-1234x"


def test_number_keeps_digit_count_and_decimal_point():
    gen = FakeGenerator("number")
    fake = gen.next("123.45")
    assert re.fullmatch(r"\d{3}\.\d{2}", fake)


def test_generated_values_are_unique_within_generator():
    gen = FakeGenerator("first_name")
    fakes = [gen.next(f"Real{i}") for i in range(200)]
    assert len(set(fakes)) == 200


def test_unknown_type_raises():
    import pytest

    with pytest.raises(ValueError, match="Unknown redaction type"):
        FakeGenerator("telepathy")
