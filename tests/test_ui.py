"""Browser-driven tests of the page itself.

`app/static/app.js` decides what a person is told about their own file. The
warnings it draws are the only thing standing between "I redacted this" and
"I sent real names to an AI tool", and none of them are reachable from the
API tests — the server can return a leak and the page can still draw
nothing. So these drive a real browser against a real server and assert on
the words on screen.

They need Playwright and its Chromium build, both dev-only: nothing here is
required to *run* SuperRedactor, and the app still needs no node toolchain.
When either is missing every test in this file skips with a message saying
what to install, so a contributor who has not run `playwright install` still
gets a green `pytest`.

    pip install -e ".[dev]"
    python -m playwright install chromium
    pytest -m ui
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import expect, sync_playwright

    PLAYWRIGHT_IMPORT_ERROR: str | None = None
except ImportError as exc:  # pragma: no cover - exercised by not installing it
    PLAYWRIGHT_IMPORT_ERROR = str(exc)
    PlaywrightError = Exception  # type: ignore[assignment,misc]
    expect = sync_playwright = None  # type: ignore[assignment]

pytestmark = pytest.mark.ui

# Generous enough for a cold CI runner, short enough that a genuinely broken
# page fails instead of hanging. The leak check is debounced ~350ms, so every
# wait below is for an element, never for a duration.
WAIT = 15_000

NO_PACKAGE = (
    "Playwright is not installed, so the browser tests cannot run "
    "({error}). Install the dev extras: pip install -e \".[dev]\""
)
NO_BROWSER = (
    "Playwright is installed but its Chromium build is not, so the browser "
    "tests cannot run. Install it with: python -m playwright install chromium"
)

# CI installs the browser on purpose, so a skip there means the UI stopped
# being covered and nobody was told. Set this and a missing browser is a
# failure instead.
REQUIRE_BROWSER = os.environ.get("SUPERREDACTOR_REQUIRE_BROWSER", "") not in ("", "0")


def _cannot_run(reason: str):
    if REQUIRE_BROWSER:
        raise RuntimeError(
            f"{reason}\n\nSUPERREDACTOR_REQUIRE_BROWSER is set, so these tests "
            f"are required to run rather than skip."
        )
    pytest.skip(reason)


# ---- a real server on a real port ----------------------------------------


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="session")
def server() -> Iterator[str]:
    """SuperRedactor, served for the length of the session.

    In-process on a thread rather than a subprocess: the page has to talk to
    the same app the rest of the suite imports, and a thread cannot outlive
    the run and leave a port held.
    """
    import uvicorn

    from app.main import app as fastapi_app

    config = uvicorn.Config(
        fastapi_app, host="127.0.0.1", port=_free_port(), log_level="warning"
    )
    running = uvicorn.Server(config)
    thread = threading.Thread(target=running.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 30
    while not running.started:
        if not thread.is_alive():
            raise RuntimeError("the test server thread died before it listened")
        if time.monotonic() > deadline:
            raise RuntimeError("the test server never finished starting up")
        time.sleep(0.02)

    yield f"http://127.0.0.1:{config.port}"

    running.should_exit = True
    thread.join(timeout=15)


# ---- a real browser, or a clear reason why not ----------------------------


@pytest.fixture(scope="session")
def browser():
    if PLAYWRIGHT_IMPORT_ERROR is not None:
        _cannot_run(NO_PACKAGE.format(error=PLAYWRIGHT_IMPORT_ERROR))
    with sync_playwright() as playwright:
        try:
            launched = playwright.chromium.launch()
        except PlaywrightError as exc:
            first_line = str(exc).strip().splitlines()[0]
            _cannot_run(f"{NO_BROWSER} ({first_line})")
        try:
            yield launched
        finally:
            launched.close()


@pytest.fixture
def page(browser, server):
    context = browser.new_context(accept_downloads=True)
    context.set_default_timeout(WAIT)
    open_page = context.new_page()
    # A thrown exception stops the rest of a render, which is how warnings
    # go missing while the page still looks alive.
    crashes: list[str] = []
    open_page.on("pageerror", lambda error: crashes.append(str(error)))
    open_page.goto(server)
    yield open_page
    context.close()
    assert not crashes, f"the page threw while the test ran: {crashes}"


# ---- helpers -------------------------------------------------------------


def _csv(tmp_path: Path, name: str, text: str) -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def _column(page, header: str):
    """The per-column dropdown on the redact screen, found the way a screen
    reader would find it."""
    return page.get_by_label(f"What to do with the column {header}", exact=True)


def _load_for_redact(page, path: str) -> None:
    page.set_input_files("#file-input", path)
    expect(page.locator("#workspace")).to_be_visible(timeout=WAIT)


def _warnings(page):
    return page.locator("#redact-warnings")


# A note quoting a client's name is exactly the leak column redaction cannot
# see: the name column is replaced, the sentence still says who it was.
LEAKY_CSV = (
    "Case ID,Client Name,Case Notes\n"
    "1001,Margaret Alvarez,Spoke with Margaret Alvarez about transport\n"
    "1002,Dennis Okonkwo,Left a voicemail for the family\n"
    "1003,Priya Raghunathan,No answer on either number\n"
)


# ==========================================================================
# the warnings that stop a leaked file being downloaded
# ==========================================================================


def test_a_value_still_visible_in_a_kept_column_is_named_on_screen(page, tmp_path):
    """The single most dangerous state this tool can be in: a column is
    replaced, the same value is sitting in a column being kept, and the
    download looks redacted."""
    _load_for_redact(page, _csv(tmp_path, "cases.csv", LEAKY_CSV))

    _column(page, "Case ID").select_option(label="Keep as is")
    _column(page, "Client Name").select_option("person_name")

    danger = _warnings(page).locator(".danger-note")
    expect(danger).to_have_count(1, timeout=WAIT)
    said = danger.inner_text()

    assert "Case Notes" in said, said        # which column still shows it
    assert "Client Name" in said, said       # where the value came from
    assert "Margaret Alvarez" in said, said  # and an example, quoted
    # Naming the problem without naming the fix leaves people downloading it
    # anyway.
    assert "Replace or remove" in said, said


def test_resolving_the_leak_gives_an_all_clear_in_words_not_an_empty_pane(
    page, tmp_path
):
    """Silence is indistinguishable from a broken check. Having actually
    looked has to be stated."""
    _load_for_redact(page, _csv(tmp_path, "cases.csv", LEAKY_CSV))
    _column(page, "Case ID").select_option(label="Keep as is")
    _column(page, "Client Name").select_option("person_name")
    expect(_warnings(page).locator(".danger-note")).to_have_count(1, timeout=WAIT)

    _column(page, "Case Notes").select_option(label="Remove this column")

    all_clear = _warnings(page).locator(".all-clear")
    expect(all_clear).to_be_visible(timeout=WAIT)
    said = all_clear.inner_text()
    assert "Checked" in said, said
    assert "appear in the columns you are keeping" in said, said
    expect(_warnings(page).locator(".danger-note")).to_have_count(0)


def test_a_check_that_could_not_run_never_reads_as_a_clean_one(page, tmp_path):
    """A failed check and a clean file must not look the same. If the
    request dies, the page says so."""
    page.route("**/api/redact/check", lambda route: route.abort())

    _load_for_redact(page, _csv(tmp_path, "cases.csv", LEAKY_CSV))
    _column(page, "Client Name").select_option("person_name")

    strip = _warnings(page).locator(".warning-strip")
    expect(strip).to_be_visible(timeout=WAIT)
    said = strip.inner_text()
    assert "Could not check" in said, said
    assert "try again" in said, said
    # Not an all-clear, and not silence.
    expect(_warnings(page).locator(".all-clear")).to_have_count(0)
    assert _warnings(page).inner_text().strip()


def test_a_column_too_small_to_hide_anyone_is_warned_about(page, tmp_path):
    """26 single-letter grades: every possible replacement is somebody's
    real grade, so replacing the column hides nobody."""
    grades = "\n".join(f"Pupil {i},{chr(ord('A') + i)}" for i in range(26))
    _load_for_redact(page, _csv(tmp_path, "marks.csv", f"Pupil,Grade\n{grades}\n"))

    _column(page, "Grade").select_option("format_preserving")

    strip = _warnings(page).locator(".warning-strip")
    expect(strip).to_be_visible(timeout=WAIT)
    said = strip.inner_text()
    assert "Grade" in said, said
    assert "too few different values" in said, said
    assert "Removing the column is safer" in said, said
    expect(_warnings(page).locator(".all-clear")).to_have_count(0)


# ==========================================================================
# templates: a file made to be shared must not carry rows out with it
# ==========================================================================

CATEGORICAL_CSV = (
    "Record Number,Status\n"
    "1001,Active\n"
    "1002,Inactive\n"
    "1003,Active\n"
    "1004,Inactive\n"
    "1005,Active\n"
    "1006,Inactive\n"
)


def _make_template(page, tmp_path) -> None:
    page.locator('.tab[data-panel="panel-standardize"]').click()
    page.locator("#std-mode-make").click()
    page.set_input_files(
        "#std-make-input", _csv(tmp_path, "referrals.csv", CATEGORICAL_CSV)
    )
    expect(page.locator("#std-make-workspace")).to_be_visible(timeout=WAIT)


def _download_template(page) -> str:
    with page.expect_download(timeout=WAIT) as caught:
        page.locator("#std-save-template").click()
    return Path(caught.value.path()).read_text(encoding="utf-8")


def test_a_new_template_remembers_no_values_until_it_is_asked_to(page, tmp_path):
    _make_template(page, tmp_path)

    boxes = page.locator("#std-columns input[type=checkbox]")
    expect(boxes).to_have_count(1)  # only the categorical column is offered
    expect(boxes).not_to_be_checked()

    # The candidates are shown as a hypothetical, not as something already
    # being carried.
    note = page.locator("#std-columns .vocab-note")
    said = note.inner_text()
    assert said.startswith("would remember:"), said
    assert "Active" in said and "Inactive" in said, said
    expect(page.locator("#std-values-warning .warning-strip")).to_have_count(0)

    in_memory = page.evaluate("stdState.template")
    assert [c for c in in_memory["columns"] if "values" in c] == []

    saved = _download_template(page)
    assert "Active" not in saved, saved
    assert "Inactive" not in saved, saved
    assert [c for c in json.loads(saved)["columns"] if "values" in c] == []


def test_ticking_remember_values_says_out_loud_that_real_data_is_now_in_it(
    page, tmp_path
):
    _make_template(page, tmp_path)
    page.locator("#std-columns input[type=checkbox]").check()

    warning = page.locator("#std-values-warning .warning-strip")
    expect(warning).to_be_visible(timeout=WAIT)
    said = warning.inner_text()
    assert "real values copied from your file" in said, said
    assert "Status" in said, said

    note = page.locator("#std-columns .vocab-note")
    assert note.inner_text().startswith("remembering:"), note.inner_text()

    saved = json.loads(_download_template(page))
    remembering = {c["name"]: c.get("values") for c in saved["columns"]}
    # Only the column that was ticked, and only its values.
    assert remembering == {"Record Number": None, "Status": ["Active", "Inactive"]}


# ==========================================================================
# error messages a person can act on
# ==========================================================================


def test_a_rejected_request_reads_as_a_sentence_not_object_object(page):
    """FastAPI answers a malformed body with a list of dicts. Rendering it
    raw put "[object Object]" on screen, which tells nobody anything."""
    status = page.evaluate(
        """async () => {
            const resp = await fetch('/api/redact/check', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: 5, config: 5 }),
            });
            return resp.status;
        }"""
    )
    assert status == 422, f"expected a validation error, got {status}"

    # Same request, through the page's own error path.
    page.evaluate(
        """() => guard('Checking…', async () => {
            await api('/api/redact/check', { session_id: 5, config: 5 });
        })()"""
    )

    banner = page.locator("#error")
    expect(banner).to_be_visible(timeout=WAIT)
    said = banner.inner_text()
    assert "[object Object]" not in said, said
    assert "undefined" not in said, said
    assert "wasn't in the expected format" in said, said


def test_a_key_file_that_matches_nothing_leaves_no_fake_text_behind(page, tmp_path):
    """Handing back the unrestored text invites someone to copy fake values
    believing they are real."""
    key = tmp_path / "DO-NOT-SHARE.cases.mapping.json"
    key.write_text(
        json.dumps(
            {
                "tool": "superredactor",
                "mapping": {
                    "Sheet1": {"Client Name": {"Margaret Alvarez": "Yolanda Fitzgerald"}}
                },
            }
        ),
        encoding="utf-8",
    )

    page.locator('.tab[data-panel="panel-deredact"]').click()
    page.set_input_files("#mapping-input", str(key))
    page.locator("#deredact-in").fill("The summary only mentions Brianna Nguyen.")
    page.locator("#deredact-btn").click()

    banner = page.locator("#error")
    expect(banner).to_be_visible(timeout=WAIT)
    assert "Nothing in that text matched" in banner.inner_text(), banner.inner_text()
    expect(page.locator("#deredact-out")).to_have_value("")
    expect(page.locator("#copy-btn")).to_be_hidden()


def test_a_redaction_key_offered_as_a_template_is_refused_by_name(page, tmp_path):
    """The key file undoes a redaction. Loading it as a template has to say
    what it actually is, and must not look accepted afterwards."""
    key = tmp_path / "DO-NOT-SHARE.cases.mapping.json"
    key.write_text(
        json.dumps({"tool": "superredactor", "mapping": {"Sheet1": {}}}),
        encoding="utf-8",
    )

    page.locator('.tab[data-panel="panel-standardize"]').click()
    page.set_input_files("#std-template-input", str(key))

    banner = page.locator("#error")
    expect(banner).to_be_visible(timeout=WAIT)
    said = banner.inner_text()
    assert "key file from a redaction" in said, said
    # Nothing was accepted: no file to standardize is asked for, and the
    # picker does not still show the rejected name.
    expect(page.locator("#std-apply-dropzone")).to_be_hidden()
    assert page.evaluate("document.getElementById('std-template-input').value") == ""
