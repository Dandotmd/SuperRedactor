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


def test_merges_mappings_across_sheets_and_columns():
    mapping = {
        "A": {"name": {"Sarah": "Maria"}},
        "B": {"id": {"101": "884"}},
    }
    assert deredact_text("Maria has id 884", mapping) == "Sarah has id 101"
