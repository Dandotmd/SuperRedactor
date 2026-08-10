from app.engine.deredact import deredact_text
from app.engine.readers import read_file
from app.engine.redactor import redact
from app.engine.writers import write_csv


def test_csv_redact_then_deredact_recovers_originals():
    data = (
        b"id,name,email,score\n"
        b"101,Sarah Chen,sarah@real.org,88\n"
        b"102,Bob Ray,bob@real.org,91\n"
        b"101,Sarah Chen,sarah@real.org,75\n"
    )
    sheets = read_file("grades.csv", data)
    config = {
        "Sheet1": {"id": "format_preserving", "name": "person_name", "email": "email"}
    }
    redacted, mapping = redact(sheets, config)

    # The redacted file still parses and keeps its shape
    back = read_file("out.csv", write_csv(redacted[0]))
    assert back[0].headers == ["id", "name", "email", "score"]
    assert len(back[0].rows) == 3

    # Nothing sensitive survives in the output
    flat = write_csv(redacted[0]).decode()
    for real in ("Sarah Chen", "Bob Ray", "sarah@real.org", "bob@real.org"):
        assert real not in flat

    # Simulated AI output containing fakes de-redacts to the originals
    fake_name = mapping["Sheet1"]["name"]["Sarah Chen"]
    fake_id = mapping["Sheet1"]["id"]["101"]
    ai_output = f"Student {fake_name} (id {fake_id}) improved."
    assert deredact_text(ai_output, mapping) == "Student Sarah Chen (id 101) improved."
