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
    assert names == {"grades.redacted.csv", "grades.mapping.json"}
    redacted = zf.read("grades.redacted.csv").decode()
    assert "Sarah Chen" not in redacted
    assert ",88" in redacted
    mapping = json.loads(zf.read("grades.mapping.json"))
    assert "Sarah Chen" in mapping["mapping"]["Sheet1"]["name"]


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
    mapping_doc = json.loads(zf.read("grades.mapping.json"))
    fake = mapping_doc["mapping"]["Sheet1"]["name"]["Sarah Chen"]

    resp = client.post(
        "/api/deredact",
        json={"mapping": mapping_doc, "text": f"{fake} did well."},
    )
    assert resp.status_code == 200
    assert resp.json()["text"] == "Sarah Chen did well."


def test_index_served():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
