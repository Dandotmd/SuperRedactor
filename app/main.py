"""FastAPI app: thin web layer over app.engine. Runs locally only —
sessions live in process memory, nothing is written to disk or sent
anywhere."""

import datetime
import io
import json
import uuid
import zipfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.engine.cleaners import clean
from app.engine.deredact import deredact_text
from app.engine.detect import suggest_type
from app.engine.fakers import REDACTION_TYPES
from app.engine.readers import read_file
from app.engine.redactor import redact
from app.engine.standardize import apply_template, make_template, match_columns
from app.engine.writers import write_csv, write_xlsx

app = FastAPI(title="SuperRedactor")

STATIC_DIR = Path(__file__).parent / "static"
PREVIEW_ROWS = 50

_sessions: dict[str, dict] = {}


class RedactRequest(BaseModel):
    session_id: str
    config: dict[str, dict[str, str]]


class DeredactRequest(BaseModel):
    mapping: dict
    text: str


class CleanRequest(BaseModel):
    session_id: str
    enabled: list[str] | None = None


class StandardizeRequest(BaseModel):
    session_id: str
    sheet: str | None = None          # sheet name; default first sheet
    template: dict | None = None
    mapping: dict[str, str | None] | None = None
    keep_extras: list[str] = []


@app.post("/api/upload")
async def upload(file: UploadFile):
    data = await file.read()
    try:
        sheets = read_file(file.filename or "upload.csv", data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    session_id = uuid.uuid4().hex
    _sessions[session_id] = {"filename": file.filename, "sheets": sheets}
    return {
        "session_id": session_id,
        "filename": file.filename,
        "redaction_types": REDACTION_TYPES,
        "sheets": [
            {
                "name": s.name,
                "headers": s.headers,
                "row_count": len(s.rows),
                "preview_rows": s.rows[:PREVIEW_ROWS],
                "suggestions": {
                    h: t for h in s.headers if (t := suggest_type(h)) is not None
                },
            }
            for s in sheets
        ],
    }


@app.post("/api/redact")
def do_redact(req: RedactRequest):
    session = _sessions.get(req.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown session — re-upload the file")
    try:
        redacted, mapping = redact(session["sheets"], req.config)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    filename: str = session["filename"]
    stem = filename.rsplit(".", 1)[0]
    is_xlsx = filename.lower().endswith(".xlsx")
    if is_xlsx:
        out_name, out_bytes = f"{stem}.redacted.xlsx", write_xlsx(redacted)
    else:
        out_name, out_bytes = f"{stem}.redacted.csv", write_csv(redacted[0])

    mapping_doc = {
        "tool": "superredactor",
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "source_file": filename,
        "mapping": mapping,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(out_name, out_bytes)
        zf.writestr(f"{stem}.mapping.json", json.dumps(mapping_doc, indent=2))
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{stem}.redacted.zip"'},
    )


def _get_session(session_id: str) -> dict:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Unknown session — re-upload the file")
    return session


@app.post("/api/clean/analyze")
def clean_analyze(req: CleanRequest):
    session = _get_session(req.session_id)
    enabled = None if req.enabled is None else set(req.enabled)
    cleaned, findings = clean(session["sheets"], enabled)
    return {
        "findings": [vars(f) for f in findings],
        "sheets": [
            {
                "name": s.name,
                "headers": s.headers,
                "row_count": len(s.rows),
                "preview_rows": s.rows[:PREVIEW_ROWS],
            }
            for s in cleaned
        ],
    }


@app.post("/api/clean/apply")
def clean_apply(req: CleanRequest):
    session = _get_session(req.session_id)
    enabled = None if req.enabled is None else set(req.enabled)
    cleaned, _ = clean(session["sheets"], enabled)

    filename: str = session["filename"]
    stem = filename.rsplit(".", 1)[0]
    if filename.lower().endswith(".xlsx"):
        out_name, out_bytes = f"{stem}.cleaned.xlsx", write_xlsx(cleaned)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        out_name, out_bytes = f"{stem}.cleaned.csv", write_csv(cleaned[0])
        media = "text/csv"
    return Response(
        content=out_bytes,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{out_name}"'},
    )


def _pick_sheet(session: dict, sheet_name: str | None):
    sheets = session["sheets"]
    if sheet_name is None:
        return sheets[0]
    for s in sheets:
        if s.name == sheet_name:
            return s
    raise HTTPException(status_code=400, detail=f"No sheet named {sheet_name!r}")


def _require_template(req: StandardizeRequest) -> dict:
    if not req.template or req.template.get("kind") != "template":
        raise HTTPException(
            status_code=400,
            detail="That file doesn't look like a SuperRedactor template.json",
        )
    return req.template


@app.post("/api/standardize/template")
def standardize_template(req: StandardizeRequest):
    session = _get_session(req.session_id)
    sheet = _pick_sheet(session, req.sheet)
    name = (session["filename"] or "template").rsplit(".", 1)[0]
    return make_template(sheet, name=name)


@app.post("/api/standardize/match")
def standardize_match(req: StandardizeRequest):
    session = _get_session(req.session_id)
    sheet = _pick_sheet(session, req.sheet)
    template = _require_template(req)
    template_cols = [c["name"] for c in template["columns"]]
    mapping = match_columns(template_cols, sheet.headers)
    used = {v for v in mapping.values() if v is not None}
    return {
        "mapping": mapping,
        "extras": [h for h in sheet.headers if h not in used],
    }


@app.post("/api/standardize/preview")
def standardize_preview(req: StandardizeRequest):
    session = _get_session(req.session_id)
    sheet = _pick_sheet(session, req.sheet)
    out, warnings = apply_template(
        sheet, _require_template(req), req.mapping or {}, req.keep_extras
    )
    return {
        "headers": out.headers,
        "row_count": len(out.rows),
        "preview_rows": out.rows[:PREVIEW_ROWS],
        "warnings": warnings,
    }


@app.post("/api/standardize/apply")
def standardize_apply(req: StandardizeRequest):
    session = _get_session(req.session_id)
    sheet = _pick_sheet(session, req.sheet)
    out, _ = apply_template(
        sheet, _require_template(req), req.mapping or {}, req.keep_extras
    )
    filename: str = session["filename"]
    stem = filename.rsplit(".", 1)[0]
    if filename.lower().endswith(".xlsx"):
        out_name, out_bytes = f"{stem}.standardized.xlsx", write_xlsx([out])
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        out_name, out_bytes = f"{stem}.standardized.csv", write_csv(out)
        media = "text/csv"
    return Response(
        content=out_bytes,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{out_name}"'},
    )


@app.post("/api/deredact")
def do_deredact(req: DeredactRequest):
    mapping = req.mapping.get("mapping", req.mapping)
    return {"text": deredact_text(req.text, mapping)}


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def run():
    import threading
    import webbrowser

    import uvicorn

    threading.Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:8321")).start()
    uvicorn.run(app, host="127.0.0.1", port=8321)
