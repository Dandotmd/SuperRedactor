"""FastAPI app: thin web layer over app.engine. Runs locally only —
sessions live in process memory, nothing is written to disk or sent
anywhere."""

import collections
import datetime
import hashlib
import io
import json
import unicodedata
import urllib.parse
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.engine.cleaners import clean
from app.engine.deredact import deredact_with_count
from app.engine.detect import suggest_type
from app.engine.fakers import REDACTION_TYPES
from app.engine.leakcheck import find_leaks, find_weak_columns
from app.engine.readers import read_file
from app.engine.redactor import redact
from app.engine.standardize import (
    apply_template,
    make_template,
    match_columns,
    suggest_sources,
)
from app.engine.writers import write_csv, write_xlsx

app = FastAPI(title="SuperRedactor")

STATIC_DIR = Path(__file__).parent / "static"
PREVIEW_ROWS = 50

_sessions: "collections.OrderedDict[str, dict]" = collections.OrderedDict()
# Each session holds a whole parsed workbook in memory, so the number of
# them is bounded. Least-recently-used is evicted, never the file someone
# is in the middle of working on — chaining between tools mints new
# sessions, so a plain count would drop the file still on screen.
MAX_SESSIONS = 24


def _safe_stem(filename: str | None) -> str:
    """The upload's name with any directory part removed.

    A file called '../../etc/passwd.csv' must not steer where anything is
    written, and its name is echoed into the download header and ZIP
    entries.
    """
    base = PurePosixPath((filename or "file").replace("\\", "/")).name
    stem = base.rsplit(".", 1)[0] if "." in base else base
    stem = "".join(c for c in stem if c.isprintable() and c != '"')
    stem = stem.strip().strip(".").strip()
    return stem or "file"


def _download(content: bytes, filename: str, media_type: str) -> Response:
    """Attachment response whose header survives non-Latin-1 filenames.

    Starlette encodes headers as Latin-1, so an em dash or an emoji in the
    name used to raise and turn every download into a 500.
    """
    ascii_name = (
        unicodedata.normalize("NFKD", filename)
        .encode("ascii", "ignore")
        .decode("ascii")
        .strip()
        or "download"
    )
    quoted = urllib.parse.quote(filename, safe="")
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quoted}'
            )
        },
    )


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


def _new_session(filename: str, sheets: list, original: bytes | None = None) -> dict:
    """Register sheets as a session and describe them the way the UI expects.
    Used both by upload and by the 'continue with this result' handoffs."""
    session_id = uuid.uuid4().hex
    while len(_sessions) >= MAX_SESSIONS:
        _sessions.pop(next(iter(_sessions)))
    _sessions[session_id] = {
        "filename": filename,
        "sheets": sheets,
        "original": original,
    }
    return {
        "session_id": session_id,
        "filename": filename,
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


@app.post("/api/upload")
async def upload(file: UploadFile):
    data = await file.read()
    try:
        sheets = read_file(file.filename or "upload.csv", data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _new_session(file.filename, sheets, original=data)


@app.post("/api/redact/check")
def redact_check(req: RedactRequest):
    """Warnings to show before anything is downloaded: values that would
    survive in columns being kept, and columns with too few possible
    replacements to hide anyone."""
    session = _get_session(req.session_id)
    sheets = session["sheets"]
    try:
        weak = find_weak_columns(sheets, req.config, seed=_run_seed(req.session_id, req.config))
    except ValueError as e:
        # Same validation the download applies, so a green all-clear can
        # never be followed by a failed download.
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "leaks": [vars(leak) for leak in find_leaks(sheets, req.config)],
        "weak_columns": [vars(column) for column in weak],
    }


@app.post("/api/redact")
def do_redact(req: RedactRequest):
    session = _get_session(req.session_id)
    try:
        redacted, mapping, weak = redact(
            session["sheets"],
            req.config,
            report=True,
            seed=_run_seed(req.session_id, req.config),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    warnings = [
        f"'{column.column}' on sheet '{column.sheet}' has too few different "
        f"values to hide — some replacements reuse a value that really "
        f"appears in this file."
        for column in weak
    ]

    filename: str = session["filename"] or "file.csv"
    stem = _safe_stem(filename)
    if filename.lower().endswith((".xlsx", ".xlsm")):
        out_name, out_bytes = f"{stem}.redacted.xlsx", write_xlsx(redacted)
    else:
        out_name, out_bytes = f"{stem}.redacted.csv", write_csv(redacted[0])

    mapping_doc = {
        "tool": "superredactor",
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "source_file": filename,
        "warnings": warnings,
        "mapping": mapping,
    }
    # The ZIP holds both the shareable file and the key that undoes it, so
    # both names have to say which is which. "staff.redacted.zip" invited
    # people to forward the whole thing.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(out_name, out_bytes)
        zf.writestr(f"DO-NOT-SHARE.{stem}.mapping.json", json.dumps(mapping_doc, indent=2))
    return _download(
        buf.getvalue(),
        f"{stem}.redacted-plus-key-DO-NOT-SHARE.zip",
        "application/zip",
    )


def _run_seed(session_id: str, config: dict) -> int:
    """A stable seed for one file and one set of choices, so the warning
    shown before the download describes the file actually downloaded."""
    material = session_id + json.dumps(config, sort_keys=True)
    return int.from_bytes(hashlib.sha256(material.encode()).digest()[:8], "big")


def _get_session(session_id: str) -> dict:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail="That file is no longer loaded. Please choose it again.",
        )
    _sessions.move_to_end(session_id)  # most recently used
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

    cleaned, findings = clean(session["sheets"], enabled)

    filename: str = session["filename"] or "file.csv"
    if (
        enabled is not None
        and not enabled
        and session.get("original") is not None
        and not any(f.always for f in findings)
    ):
        # "No fixes selected" has to mean the file comes back untouched.
        # Rewriting it would still introduce parser artifacts like padded
        # rows and invented headings for unnamed columns. Skipped when
        # something non-optional applies, so that stays true to its word.
        return _download(
            session["original"],
            filename,
            "application/octet-stream",
        )

    stem = _safe_stem(filename)
    if filename.lower().endswith((".xlsx", ".xlsm")):
        out_name, out_bytes = f"{stem}.cleaned.xlsx", write_xlsx(cleaned)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        out_name, out_bytes = f"{stem}.cleaned.csv", write_csv(cleaned[0])
        media = "text/csv"
    return _download(out_bytes, out_name, media)


def _pick_sheet(session: dict, sheet_name: str | None):
    sheets = session["sheets"]
    if sheet_name is None:
        return sheets[0]
    for s in sheets:
        if s.name == sheet_name:
            return s
    raise HTTPException(status_code=400, detail=f"No sheet named {sheet_name!r}")


def _require_template(req: StandardizeRequest) -> dict:
    bad = (
        "That file doesn't look like a SuperRedactor template. Make one on the "
        "'Make a template' screen and save it, then choose that file here."
    )
    template = req.template
    if not template or template.get("kind") != "template":
        raise HTTPException(status_code=400, detail=bad)
    columns = template.get("columns")
    if not isinstance(columns, list) or not columns:
        raise HTTPException(
            status_code=400,
            detail="That template has no columns in it, so there is nothing to "
            "standardize onto. Make the template again from an example file.",
        )
    for column in columns:
        if not isinstance(column, dict) or not isinstance(column.get("name"), str):
            raise HTTPException(status_code=400, detail=bad)
        column.setdefault("type", "text")
        if column["type"] not in ("text", "date", "number"):
            column["type"] = "text"
        # Templates are meant to be committed and hand-edited, so anything
        # in here may have been typed by a person. Keep the usable parts
        # and drop the rest rather than failing on the whole file.
        aliases = column.get("aliases")
        if isinstance(aliases, dict):
            column["aliases"] = {
                k: v
                for k, v in aliases.items()
                if isinstance(k, str) and isinstance(v, str)
            }
        elif aliases is not None:
            column["aliases"] = {}
        values = column.get("values")
        if isinstance(values, list):
            column["values"] = [v for v in values if isinstance(v, str)]
            if not column["values"]:
                column.pop("values")
        elif values is not None:
            column.pop("values")
    return template


def _check_columns_exist(sheet, req: StandardizeRequest) -> None:
    known = set(sheet.headers)
    for target, source in (req.mapping or {}).items():
        if source is not None and source not in known:
            raise HTTPException(
                status_code=400,
                detail=f"This file has no column called '{source}'. Choose one of "
                f"its own columns for '{target}', or leave it empty.",
            )
    for extra in req.keep_extras:
        if extra not in known:
            raise HTTPException(
                status_code=400,
                detail=f"This file has no column called '{extra}' to keep.",
            )


@app.post("/api/clean/commit")
def clean_commit(req: CleanRequest):
    """Hand the cleaned data to the next tool without a re-upload. The
    original session is left intact so 'start over' still works."""
    session = _get_session(req.session_id)
    enabled = None if req.enabled is None else set(req.enabled)
    cleaned, _ = clean(session["sheets"], enabled)
    return _new_session(session["filename"], cleaned)


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
        "suggestions": suggest_sources(template_cols, sheet.headers, mapping),
    }


@app.post("/api/standardize/preview")
def standardize_preview(req: StandardizeRequest):
    session = _get_session(req.session_id)
    sheet = _pick_sheet(session, req.sheet)
    _require_template(req)
    _check_columns_exist(sheet, req)
    result = apply_template(
        sheet, _require_template(req), req.mapping or {}, req.keep_extras
    )
    return {
        "headers": result.sheet.headers,
        "row_count": len(result.sheet.rows),
        "preview_rows": result.sheet.rows[:PREVIEW_ROWS],
        "warnings": result.warnings,
        "unmatched": result.unmatched,
        "vocabularies": {
            c["name"]: c["values"]
            for c in _require_template(req)["columns"]
            if c.get("values")
        },
    }


@app.post("/api/standardize/apply")
def standardize_apply(req: StandardizeRequest):
    session = _get_session(req.session_id)
    sheet = _pick_sheet(session, req.sheet)
    _require_template(req)
    _check_columns_exist(sheet, req)
    out = apply_template(
        sheet, _require_template(req), req.mapping or {}, req.keep_extras
    ).sheet
    filename: str = session["filename"] or "file.csv"
    stem = _safe_stem(filename)
    if filename.lower().endswith((".xlsx", ".xlsm")):
        out_name, out_bytes = f"{stem}.standardized.xlsx", write_xlsx([out])
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        out_name, out_bytes = f"{stem}.standardized.csv", write_csv(out)
        media = "text/csv"
    return _download(out_bytes, out_name, media)


@app.post("/api/standardize/commit")
def standardize_commit(req: StandardizeRequest):
    session = _get_session(req.session_id)
    sheet = _pick_sheet(session, req.sheet)
    _require_template(req)
    _check_columns_exist(sheet, req)
    out = apply_template(
        sheet, _require_template(req), req.mapping or {}, req.keep_extras
    ).sheet
    return _new_session(session["filename"], [out])


@app.post("/api/deredact")
def do_deredact(req: DeredactRequest):
    if req.mapping.get("kind") == "template":
        raise HTTPException(
            status_code=400,
            detail="That's a template file, not a key file. The key is the "
            "DO-NOT-SHARE…mapping.json from the ZIP you downloaded when you "
            "redacted.",
        )
    mapping = req.mapping.get("mapping", req.mapping)
    if not isinstance(mapping, dict):
        raise HTTPException(
            status_code=400,
            detail="That key file isn't in the expected format. Use the "
            "mapping.json from the ZIP you downloaded when you redacted.",
        )
    text, replacements = deredact_with_count(req.text, mapping)
    return {"text": text, "replacements": replacements}


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.ico")
def favicon():
    # The page supplies its own inline icon; browsers ask for this anyway.
    return Response(status_code=204)


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


DEFAULT_PORT = 8321


def _free_port(start: int = DEFAULT_PORT, tries: int = 10) -> int | None:
    """First free port at or after `start`.

    Double-clicking the launcher twice used to end in a bind error and a
    stack trace, which tells someone non-technical nothing.
    """
    import socket

    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return None


def run():
    import threading
    import webbrowser

    import uvicorn

    port = _free_port()
    if port is None:
        print(
            "\nSuperRedactor could not start: ports 8321-8330 are all busy on this\n"
            "computer. It is probably already running — look for it at\n"
            "http://127.0.0.1:8321 in your browser, or restart your computer\n"
            "and try again.\n"
        )
        raise SystemExit(1)

    url = f"http://127.0.0.1:{port}"
    if port != DEFAULT_PORT:
        print(f"\nPort {DEFAULT_PORT} was busy, so SuperRedactor is using {url}\n")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=port)
