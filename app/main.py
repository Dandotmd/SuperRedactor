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

from app.engine.deredact import deredact_text
from app.engine.detect import suggest_type
from app.engine.fakers import REDACTION_TYPES
from app.engine.readers import read_file
from app.engine.redactor import redact
from app.engine.writers import write_csv, write_xlsx

app = FastAPI(title="PII Redactor")

STATIC_DIR = Path(__file__).parent / "static"
PREVIEW_ROWS = 50

_sessions: dict[str, dict] = {}


class RedactRequest(BaseModel):
    session_id: str
    config: dict[str, dict[str, str]]


class DeredactRequest(BaseModel):
    mapping: dict
    text: str


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
        "tool": "pii-redactor",
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
