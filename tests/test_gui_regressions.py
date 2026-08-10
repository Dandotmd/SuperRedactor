"""Regressions for problems found by driving the UI as a non-technical user.

The theme: the app made confident promises ("safe to share", "none of the
data") that the code did not keep.
"""

import io
import json
import zipfile

from fastapi.testclient import TestClient

from app.engine.readers import Sheet
from app.engine.standardize import make_template
from app.main import app

client = TestClient(app)


def upload(name: str, data: bytes) -> dict:
    return client.post(
        "/api/upload", files={"file": (name, io.BytesIO(data), "text/csv")}
    ).json()


# ---- free text keeps what the redaction hid --------------------------------

CASE_NOTES = (
    b"Case ID,Client Name,Case Notes\n"
    b"ER-73,Margaret Alvarez,Spoke with Margaret Alvarez about her medication\n"
    b"TD-08,Robert Higgins,Left a message\n"
)


def test_check_reports_a_name_quoted_in_a_kept_notes_column():
    session = upload("casenotes.csv", CASE_NOTES)
    body = client.post(
        "/api/redact/check",
        json={
            "session_id": session["session_id"],
            "config": {"Sheet1": {"Client Name": "person_name"}},
        },
    ).json()
    assert body["leaks"], "a redacted name quoted in Case Notes must be reported"
    assert body["leaks"][0]["kept_column"] == "Case Notes"


# ---- templates must not carry real values ---------------------------------

def test_template_does_not_remember_values_of_personal_columns():
    sheet = Sheet(
        name="S",
        headers=["Client Name", "Program"],
        # A visit log repeats the same clients, so the vocabulary rule would
        # otherwise capture their real names into a shareable template.
        rows=[
            [name, program]
            for name, program in [
                ("Henry Yu", "Housing"),
                ("Mei Tanaka", "Housing"),
                ("Rosa Delgado", "Treatment"),
            ]
            * 3
        ],
    )
    template = make_template(sheet, name="t")
    columns = {c["name"]: c for c in template["columns"]}
    assert "values" not in columns["Client Name"]
    assert columns["Program"]["values"] == ["Housing", "Treatment"]


def test_template_reports_which_columns_carry_example_values():
    session = upload(
        "visits.csv",
        b"Program,Status\n"
        b"Housing,active\nTreatment,active\nHousing,closed\n"
        b"Housing,active\nTreatment,closed\nTreatment,active\n",
    )
    template = client.post(
        "/api/standardize/template", json={"session_id": session["session_id"]}
    ).json()
    assert template["columns_with_values"] == ["Program", "Status"]


# ---- the key file must announce itself ------------------------------------

def test_zip_and_key_names_say_the_key_must_not_be_shared():
    session = upload("staff.csv", b"name,score\nAda,88\nGrace,91\n")
    resp = client.post(
        "/api/redact",
        json={"session_id": session["session_id"], "config": {"Sheet1": {"name": "person_name"}}},
    )
    names = zipfile.ZipFile(io.BytesIO(resp.content)).namelist()
    key = [n for n in names if n.endswith(".json")][0]
    assert "DO-NOT-SHARE" in key
    assert "DO-NOT-SHARE" in resp.headers["content-disposition"]


# ---- standardize should suggest the obvious column ------------------------

def test_match_suggests_a_likely_column_for_unmatched_template_entries():
    session = upload(
        "other.csv", b"Client ID,Full Name,state,Amout\n9001,Ada,active,50\n"
    )
    template = {
        "kind": "template",
        "version": 1,
        "name": "t",
        "columns": [
            {"name": "Client ID", "type": "text"},
            {"name": "Client Name", "type": "text"},
            {"name": "Status", "type": "text"},
            {"name": "Amount Due", "type": "number"},
        ],
    }
    body = client.post(
        "/api/standardize/match",
        json={"session_id": session["session_id"], "template": template},
    ).json()
    assert body["suggestions"]["Client Name"] == "Full Name"
    assert body["suggestions"]["Amount Due"] == "Amout"


# ---- untouched means untouched --------------------------------------------

MESSY = b"Quarterly Extract,,\nName,Score,\nAda,88,\nGrace,91,\n"


def test_cleaning_with_no_fixes_returns_the_original_file_unchanged():
    session = upload("messy.csv", MESSY)
    resp = client.post(
        "/api/clean/apply", json={"session_id": session["session_id"], "enabled": []}
    )
    assert resp.content == MESSY


def test_cleaning_with_fixes_still_transforms():
    session = upload("messy.csv", MESSY)
    findings = client.post(
        "/api/clean/analyze", json={"session_id": session["session_id"]}
    ).json()["findings"]
    resp = client.post(
        "/api/clean/apply",
        json={"session_id": session["session_id"], "enabled": [f["id"] for f in findings]},
    )
    assert resp.content != MESSY
    assert resp.content.splitlines()[0] == b"Name,Score"


# ---- a template is not a key file -----------------------------------------

def test_using_a_template_as_the_key_file_says_so():
    template = {"kind": "template", "version": 1, "name": "t", "columns": []}
    resp = client.post("/api/deredact", json={"mapping": template, "text": "hello"})
    assert resp.status_code == 400
    assert "template" in resp.json()["detail"].lower()


def test_favicon_does_not_404():
    assert client.get("/favicon.ico").status_code in (200, 204)
