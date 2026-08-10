import io
import json
import zipfile

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

CSV = b"name,email,score\nSarah Chen,sarah@real.org,88\nBob Ray,bob@real.org,91\n"


def upload_csv():
    return client.post(
        "/api/upload", files={"file": ("grades.csv", io.BytesIO(CSV), "text/csv")}
    )


def test_upload_returns_preview_and_suggestions():
    resp = upload_csv()
    assert resp.status_code == 200
    body = resp.json()
    assert body["filename"] == "grades.csv"
    assert body["session_id"]
    sheet = body["sheets"][0]
    assert sheet["headers"] == ["name", "email", "score"]
    assert sheet["suggestions"] == {"name": "person_name", "email": "email"}
    assert sheet["preview_rows"][0] == ["Sarah Chen", "sarah@real.org", "88"]
    assert sheet["row_count"] == 2


def test_upload_rejects_unsupported_type():
    resp = client.post(
        "/api/upload", files={"file": ("x.parquet", io.BytesIO(b"x"), "application/x")}
    )
    assert resp.status_code == 400


def test_redact_returns_zip_with_file_and_mapping():
    session_id = upload_csv().json()["session_id"]
    resp = client.post(
        "/api/redact",
        json={
            "session_id": session_id,
            "config": {"Sheet1": {"name": "person_name", "email": "email"}},
        },
    )
    assert resp.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = set(zf.namelist())
    assert names == {"grades.redacted.csv", "DO-NOT-SHARE.grades.mapping.json"}
    redacted = zf.read("grades.redacted.csv").decode()
    assert "Sarah Chen" not in redacted
    assert ",88" in redacted
    mapping = json.loads(zf.read("DO-NOT-SHARE.grades.mapping.json"))
    assert "Sarah Chen" in mapping["mapping"]["Sheet1"]["name"]


LEAKY_CSV = (
    b"name,emergency_contact,score\n"
    b"Sarah Chen,Sarah Chen,88\n"
    b"Bob Ray,Ann Ray,91\n"
)


def test_redact_check_warns_about_values_kept_elsewhere():
    session_id = upload_bytes("leaky.csv", LEAKY_CSV)
    body = client.post(
        "/api/redact/check",
        json={"session_id": session_id, "config": {"Sheet1": {"name": "person_name"}}},
    ).json()
    assert len(body["leaks"]) == 1
    leak = body["leaks"][0]
    assert leak["kept_column"] == "emergency_contact"
    assert leak["redacted_column"] == "name"


def test_redact_check_silent_when_no_leak():
    session_id = upload_bytes("leaky.csv", LEAKY_CSV)
    body = client.post(
        "/api/redact/check",
        json={
            "session_id": session_id,
            "config": {"Sheet1": {"name": "person_name", "emergency_contact": "person_name"}},
        },
    ).json()
    assert body["leaks"] == []


def test_redact_unknown_session_404():
    resp = client.post("/api/redact", json={"session_id": "nope", "config": {}})
    assert resp.status_code == 404


def test_deredact_translates_text():
    session_id = upload_csv().json()["session_id"]
    zip_resp = client.post(
        "/api/redact",
        json={"session_id": session_id, "config": {"Sheet1": {"name": "person_name"}}},
    )
    zf = zipfile.ZipFile(io.BytesIO(zip_resp.content))
    mapping_doc = json.loads(zf.read("DO-NOT-SHARE.grades.mapping.json"))
    fake = mapping_doc["mapping"]["Sheet1"]["name"]["Sarah Chen"]

    resp = client.post(
        "/api/deredact",
        json={"mapping": mapping_doc, "text": f"{fake} did well."},
    )
    assert resp.status_code == 200
    assert resp.json()["text"] == "Sarah Chen did well."
    assert resp.json()["replacements"] == 1


def test_deredact_reports_zero_replacements_for_unrelated_text():
    body = client.post(
        "/api/deredact",
        json={"mapping": {"S": {"c": {"real": "fake"}}}, "text": "nothing here"},
    ).json()
    assert body["replacements"] == 0


MESSY_CSV = (
    b"Quarterly Report,,\n"
    b",,\n"
    b"Name,Amount,Seen\n"
    b"  Sarah  Chen ,\"$1,234.56\",3/12/2024\n"
    b"Bob Ray,300,2024-03-15\n"
    b"Bob Ray,300,2024-03-15\n"
    b"Maya Ortiz,\"$2,000\",\"Mar 20, 2024\"\n"
    b"Total,,\n"
)


def upload_messy():
    return client.post(
        "/api/upload", files={"file": ("messy.csv", io.BytesIO(MESSY_CSV), "text/csv")}
    )


def test_clean_analyze_returns_findings_and_preview():
    session_id = upload_messy().json()["session_id"]
    resp = client.post("/api/clean/analyze", json={"session_id": session_id})
    assert resp.status_code == 200
    body = resp.json()
    kinds = {f["kind"] for f in body["findings"]}
    assert {"title_rows", "trailing_junk", "duplicate_rows", "whitespace",
            "numbers_as_text", "date_formats"} <= kinds
    preview = body["sheets"][0]
    assert preview["headers"] == ["Name", "Amount", "Seen"]
    assert preview["preview_rows"][0] == ["Sarah Chen", "1234.56", "2024-03-12"]


def test_clean_analyze_with_subset_updates_preview():
    session_id = upload_messy().json()["session_id"]
    all_ids = [
        f["id"] for f in
        client.post("/api/clean/analyze", json={"session_id": session_id}).json()["findings"]
    ]
    subset = [i for i in all_ids if not i.startswith("duplicate_rows")]
    body = client.post(
        "/api/clean/analyze", json={"session_id": session_id, "enabled": subset}
    ).json()
    rows = body["sheets"][0]["preview_rows"]
    assert rows.count(["Bob Ray", "300", "2024-03-15"]) == 2


def test_clean_apply_downloads_cleaned_file():
    session_id = upload_messy().json()["session_id"]
    all_ids = [
        f["id"] for f in
        client.post("/api/clean/analyze", json={"session_id": session_id}).json()["findings"]
    ]
    resp = client.post(
        "/api/clean/apply", json={"session_id": session_id, "enabled": all_ids}
    )
    assert resp.status_code == 200
    text = resp.content.decode()
    assert text.splitlines()[0] == "Name,Amount,Seen"
    assert "Quarterly Report" not in text and "Total" not in text
    assert "messy.cleaned.csv" in resp.headers["content-disposition"]


def test_clean_unknown_session_404():
    resp = client.post("/api/clean/analyze", json={"session_id": "nope"})
    assert resp.status_code == 404


GOOD_CSV = (
    b"student_id,name,email,dob\n"
    b"S-1001,Sarah Chen,s@x.org,2014-03-12\n"
    b"S-1002,Bob Ray,b@x.org,2013-11-02\n"
    b"S-1003,Maya Ortiz,m@x.org,2014-07-30\n"
)
SYSTEM_B_CSV = (
    b"Student Name,BirthDate,ID,Homeroom\n"
    b"Sarah Chen,3/12/2014,S-1001,12B\n"
    b"Bob Ray,11/2/2013,S-1002,9A\n"
)


def upload_bytes(name, data):
    return client.post(
        "/api/upload", files={"file": (name, io.BytesIO(data), "text/csv")}
    ).json()["session_id"]


def make_template_via_api():
    session_id = upload_bytes("students.csv", GOOD_CSV)
    return client.post(
        "/api/standardize/template", json={"session_id": session_id}
    ).json()["template"]


def test_standardize_template_from_upload():
    template = make_template_via_api()
    assert template["kind"] == "template"
    assert [c["name"] for c in template["columns"]] == ["student_id", "name", "email", "dob"]
    assert template["columns"][3]["type"] == "date"


def test_standardize_match_proposes_mapping_and_extras():
    template = make_template_via_api()
    session_id = upload_bytes("system_b.csv", SYSTEM_B_CSV)
    body = client.post(
        "/api/standardize/match",
        json={"session_id": session_id, "template": template},
    ).json()
    assert body["mapping"]["name"] == "Student Name"
    assert body["mapping"]["dob"] == "BirthDate"
    assert body["mapping"]["email"] is None
    assert body["extras"] == ["Homeroom"]


def test_standardize_preview_and_apply():
    template = make_template_via_api()
    session_id = upload_bytes("system_b.csv", SYSTEM_B_CSV)
    mapping = client.post(
        "/api/standardize/match",
        json={"session_id": session_id, "template": template},
    ).json()["mapping"]

    preview = client.post(
        "/api/standardize/preview",
        json={
            "session_id": session_id, "template": template,
            "mapping": mapping, "keep_extras": ["Homeroom"],
        },
    ).json()
    assert preview["headers"] == ["student_id", "name", "email", "dob", "Homeroom"]
    assert preview["preview_rows"][0] == ["S-1001", "Sarah Chen", "", "2014-03-12", "12B"]
    assert any("email" in w for w in preview["warnings"])

    resp = client.post(
        "/api/standardize/apply",
        json={
            "session_id": session_id, "template": template,
            "mapping": mapping, "keep_extras": [],
        },
    )
    assert resp.status_code == 200
    lines = resp.content.decode().splitlines()
    assert lines[0] == "student_id,name,email,dob"
    assert "system_b.standardized.csv" in resp.headers["content-disposition"]


def test_standardize_unknown_session_404():
    template = make_template_via_api()
    resp = client.post(
        "/api/standardize/match", json={"session_id": "nope", "template": template}
    )
    assert resp.status_code == 404


def test_clean_commit_returns_new_session_with_cleaned_data():
    session_id = upload_messy().json()["session_id"]
    findings = client.post(
        "/api/clean/analyze", json={"session_id": session_id}
    ).json()["findings"]
    body = client.post(
        "/api/clean/commit",
        json={"session_id": session_id, "enabled": [f["id"] for f in findings]},
    ).json()

    assert body["session_id"] != session_id
    assert body["sheets"][0]["headers"] == ["Name", "Amount", "Seen"]
    # the derived session is usable by the other tools
    redacted = client.post(
        "/api/redact",
        json={"session_id": body["session_id"], "config": {"Sheet1": {"Name": "person_name"}}},
    )
    assert redacted.status_code == 200


def test_original_session_survives_commit():
    session_id = upload_messy().json()["session_id"]
    client.post("/api/clean/commit", json={"session_id": session_id, "enabled": []})
    again = client.post("/api/clean/analyze", json={"session_id": session_id})
    assert again.status_code == 200
    assert again.json()["findings"]


def test_standardize_commit_returns_new_session():
    template = make_template_via_api()
    session_id = upload_bytes("system_b.csv", SYSTEM_B_CSV)
    mapping = client.post(
        "/api/standardize/match", json={"session_id": session_id, "template": template}
    ).json()["mapping"]
    body = client.post(
        "/api/standardize/commit",
        json={
            "session_id": session_id, "template": template,
            "mapping": mapping, "keep_extras": [],
        },
    ).json()
    assert body["sheets"][0]["headers"] == ["student_id", "name", "email", "dob"]
    assert body["sheets"][0]["suggestions"]["name"] == "person_name"


def test_index_served():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
