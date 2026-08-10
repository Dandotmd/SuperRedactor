"""Regressions for API-level failures found by adversarial testing:
filenames with smart punctuation crashed every download, and hostile
filenames flowed unsanitized into download headers and ZIP entries.
"""

import io
import json
import zipfile

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

CSV = b"name,score\nAda Lovelace,88\nGrace Hopper,91\n"


def upload(name: str):
    return client.post(
        "/api/upload", files={"file": (name, io.BytesIO(CSV), "text/csv")}
    ).json()["session_id"]


def redact(session_id: str):
    return client.post(
        "/api/redact",
        json={"session_id": session_id, "config": {"Sheet1": {"name": "person_name"}}},
    )


def test_filename_with_smart_punctuation_downloads():
    # macOS substitutes em dashes and curly apostrophes automatically
    resp = redact(upload("Roster — Ada’s class.csv"))
    assert resp.status_code == 200
    assert zipfile.ZipFile(io.BytesIO(resp.content)).namelist()


def test_non_latin_filename_downloads():
    resp = redact(upload("学生名簿.csv"))
    assert resp.status_code == 200


def test_emoji_filename_downloads():
    resp = redact(upload("roster 🎓.csv"))
    assert resp.status_code == 200


def test_download_header_is_ascii_safe():
    resp = redact(upload("Roster — Ada’s class.csv"))
    disposition = resp.headers["content-disposition"]
    disposition.encode("latin-1")  # would raise if unsafe
    assert "filename*=" in disposition


def test_path_traversal_filename_is_stripped():
    resp = redact(upload("../../../../etc/passwd.csv"))
    assert resp.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(resp.content)).namelist()
    for name in names:
        assert ".." not in name and not name.startswith("/")
    assert "passwd" in resp.headers["content-disposition"]


def test_absolute_path_filename_is_stripped():
    resp = redact(upload("/etc/cron.d/pwn.csv"))
    names = zipfile.ZipFile(io.BytesIO(resp.content)).namelist()
    assert all(not n.startswith("/") for n in names)


def test_cleaned_download_survives_odd_filename():
    session_id = upload("Roster — Ada’s class.csv")
    resp = client.post("/api/clean/apply", json={"session_id": session_id, "enabled": []})
    assert resp.status_code == 200


def test_mac_line_endings_upload_cleanly():
    resp = client.post(
        "/api/upload",
        files={"file": ("mac.csv", io.BytesIO(b"name,score\rAda,88\rGrace,91\r"), "text/csv")},
    )
    assert resp.status_code == 200
    assert resp.json()["sheets"][0]["row_count"] == 2


def test_huge_cell_upload_cleanly():
    data = ("name,notes\nAda," + "x" * 200_000 + "\n").encode()
    resp = client.post(
        "/api/upload", files={"file": ("big.csv", io.BytesIO(data), "text/csv")}
    )
    assert resp.status_code == 200


def test_redact_config_naming_a_missing_sheet_is_rejected():
    session_id = upload("x.csv")
    resp = client.post(
        "/api/redact",
        json={"session_id": session_id, "config": {"Nope": {"name": "person_name"}}},
    )
    assert resp.status_code == 400
    assert "Nope" in resp.json()["detail"]


def test_redact_warns_about_columns_too_small_to_hide():
    rows = "\n".join(f"{chr(65 + i)}" for i in range(26))
    data = f"grade\n{rows}\n".encode()
    session_id = client.post(
        "/api/upload", files={"file": ("g.csv", io.BytesIO(data), "text/csv")}
    ).json()["session_id"]
    body = client.post(
        "/api/redact/check",
        json={"session_id": session_id, "config": {"Sheet1": {"grade": "format_preserving"}}},
    ).json()
    assert body["weak_columns"]


# ---- standardize input validation -----------------------------------------

def make_template():
    session_id = upload("t.csv")
    return client.post(
        "/api/standardize/template", json={"session_id": session_id}
    ).json()


def test_template_without_columns_is_rejected():
    session_id = upload("x.csv")
    for bad in (
        {"kind": "template"},
        {"kind": "template", "columns": []},
        {"kind": "template", "columns": "nope"},
        {"kind": "template", "columns": ["nope"]},
        {"kind": "template", "columns": [{"nope": 1}]},
    ):
        resp = client.post(
            "/api/standardize/match", json={"session_id": session_id, "template": bad}
        )
        assert resp.status_code == 400, bad


def test_mapping_to_a_missing_column_is_rejected():
    session_id = upload("x.csv")
    template = make_template()
    resp = client.post(
        "/api/standardize/preview",
        json={
            "session_id": session_id,
            "template": template,
            "mapping": {"name": "Not A Column"},
            "keep_extras": [],
        },
    )
    assert resp.status_code == 400
    assert "Not A Column" in resp.json()["detail"]


def test_run_picks_a_free_port_when_the_default_is_busy():
    import socket

    from app.main import DEFAULT_PORT, _free_port

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as taken:
        taken.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        taken.bind(("127.0.0.1", DEFAULT_PORT))
        taken.listen(1)
        assert _free_port() != DEFAULT_PORT


def test_keep_extras_naming_a_missing_column_is_rejected():
    session_id = upload("x.csv")
    template = make_template()
    resp = client.post(
        "/api/standardize/preview",
        json={
            "session_id": session_id,
            "template": template,
            "mapping": {"name": "name"},
            "keep_extras": ["Ghost"],
        },
    )
    assert resp.status_code == 400
