from app.engine.deredact import deredact_text


def nested(pairs: dict[str, str]) -> dict:
    return {"Sheet1": {"name": pairs}}


def test_replaces_fake_with_real():
    mapping = nested({"Sarah Chen": "Maria Lopez"})
    assert deredact_text("Maria Lopez scored highest.", mapping) == (
        "Sarah Chen scored highest."
    )


def test_replaces_all_occurrences():
    mapping = nested({"Sarah Chen": "Maria Lopez"})
    out = deredact_text("Maria Lopez and Maria Lopez again", mapping)
    assert out == "Sarah Chen and Sarah Chen again"


def test_longer_fakes_replaced_before_substrings():
    mapping = {
        "Sheet1": {
            "first": {"Ann": "Maria"},
            "full": {"Ann Smith": "Maria Lopez"},
        }
    }
    assert deredact_text("Maria Lopez won.", mapping) == "Ann Smith won."


def test_text_without_fakes_unchanged():
    mapping = nested({"Sarah Chen": "Maria Lopez"})
    assert deredact_text("Nothing to see here.", mapping) == "Nothing to see here."


def test_short_numeric_fakes_do_not_corrupt_unrelated_numbers():
    # fake "3" must not rewrite the 3 inside "350"
    mapping = nested({"7": "3", "9": "5"})
    out = deredact_text("3 students scored above 85; cohort of 350.", mapping)
    assert out == "7 students scored above 85; cohort of 350."


def test_fake_that_is_a_common_word_only_matches_whole_words():
    mapping = nested({"Ada Lovelace": "is"})
    out = deredact_text("This is a list of students.", mapping)
    assert out == "This Ada Lovelace a list of students."


def test_values_with_punctuation_still_match():
    mapping = nested({"sarah@real.org": "dylan86@example.com"})
    out = deredact_text("Email dylan86@example.com, please.", mapping)
    assert out == "Email sarah@real.org, please."


def test_merges_mappings_across_sheets_and_columns():
    mapping = {
        "A": {"name": {"Sarah": "Maria"}},
        "B": {"id": {"101": "884"}},
    }
    assert deredact_text("Maria has id 884", mapping) == "Sarah has id 101"
