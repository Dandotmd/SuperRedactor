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


def test_index_served():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
