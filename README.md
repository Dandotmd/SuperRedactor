# SuperRedactor

A local web app for getting spreadsheets ready to share with AI tools when the
data is too sensitive to upload. It runs on your own computer, in your browser,
and never sends anything anywhere.

It does four things:

| | |
|---|---|
| **Redact personal info** | Replace names, emails, SSNs and other personal columns with realistic fake data. You get a key file to turn the fakes back into real values later. |
| **Clean up a file** | Fix a badly exported spreadsheet: title rows above the headings, totals at the bottom, duplicates, stray spaces, `N/A` markers, `$1,234`-style numbers, mixed date formats. |
| **Standardize** | Make files from different systems come out with the same columns in the same order, every time, using a template you save once. |
| **Restore real values** | Turn the fake values in an AI's answer back into the real ones. |

You can pass a file from one step to the next without re-uploading it.

**Everything runs on your machine. Nothing is uploaded anywhere, ever.**

## Why

If you work with regulated or confidential data (FERPA, HIPAA, PII covered by
the Privacy Act, or plain "don't leak the customer list"), you can't paste real
exports into an AI tool. But you still want AI help building dashboards,
scripts, and analyses around that data. Redact first, build against the fakes,
restore the results.

Because the fake data is realistic — fake names stay names, fake SSNs look like
SSNs, IDs keep their exact format — anything the AI builds against the redacted
file works unchanged on the real one.

## Privacy & security posture

Designed so a security reviewer can verify every claim by reading a small
amount of code:

- **Localhost only.** The server binds to `127.0.0.1:8321` and is unreachable
  from the network.
- **Zero outbound requests.** No telemetry, no update checks, no CDN scripts,
  no font downloads. The page is fully self-contained; the codebase contains
  no HTTP client.
- **No server-side persistence.** Uploaded files live in process memory only
  and vanish when the server stops. Nothing is written to disk except the file
  you explicitly download.
- **Small, auditable dependency list**: FastAPI, uvicorn, python-multipart,
  openpyxl, Faker. The engine (`app/engine/`) is pure Python with no web
  dependencies.
- **Formula injection is neutralized.** Cells starting with `=`, `+`, `-` or
  `@` can execute when a CSV is opened in Excel. Clean up detects them and
  makes them safe as text.
- **The key file is the risk.** `mapping.json` is the only path from fake
  values back to real ones. Treat it exactly like the source data: keep it on
  your machine, never attach it to the file you're sharing.

## Install & run

Requires Python 3.10 or newer. No admin rights needed.

```bash
git clone https://github.com/Dandotmd/SuperRedactor.git
cd SuperRedactor
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
superredactor
```

Your browser opens at `http://127.0.0.1:8321`. Stop it with `Ctrl+C` in the
terminal; everything it held in memory is gone.

Equivalent, without installing the command:

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8321
```

## Install on locked-down / government computers

You often can't run arbitrary installers or reach the open internet from a work
machine. Options, in order of preference:

**1. No git? Download a ZIP.**
On GitHub, *Code → Download ZIP*, transfer it by your approved method, unzip,
and follow the normal steps — git is not required to run the tool.

**2. Python without admin rights.**
The python.org installer supports a per-user install (no elevation), or use
whatever your agency's software center provides. Any CPython 3.10+ works. On
Windows, if `python3` isn't found, try `py -3` or `python`.

**3. pip behind a corporate proxy / TLS inspection.**
If `pip install` fails with certificate errors, your agency likely intercepts
TLS. Point pip at your organization's CA bundle (ask IT for the `.pem`):

```bash
pip config set global.cert /path/to/agency-ca-bundle.pem
```

Set `HTTPS_PROXY` if your network requires it. Do **not** disable certificate
verification.

**4. Fully offline (air-gapped) install.**
On any internet-connected machine with the same OS and Python major version:

```bash
pip download -d wheels .
```

Transfer the project folder plus `wheels/` on approved media, then on the
offline machine:

```bash
pip install --no-index --find-links wheels -e .
```

**5. Verify before you trust.**
The claims above are checkable: `grep` the codebase for `http` — the only
network code is the uvicorn server bound to `127.0.0.1`. Run `pytest` to
exercise the whole engine. Your agency's rules for handling the *source* data
still apply to the machine you run this on and to `mapping.json`.

> SuperRedactor is an independent open-source tool. It is not produced or
> endorsed by any government agency. Redacting a file does not by itself make
> it releasable — follow your organization's data-handling policy.

## Using it

Files can be `.csv` or `.xlsx` (also `.tsv`, `.txt`, `.xlsm`). Odd delimiters
(comma, pipe, tab, semicolon), Latin-1/Windows encodings, ragged rows, and
files with no header row are all handled automatically. Legacy `.xls` is not
supported — open it in Excel and save as `.xlsx` first.

### Redact personal info

1. Drop in your file. Columns that look personal are pre-marked from their
   names — **check every column yourself**; the suggestions are heuristics.
2. Set each column to keep, replace with a type of fake data, or remove.
   Marked columns preview as black bars.
3. Download the ZIP: your redacted file plus `mapping.json`.

Within one run the same real value always becomes the same fake value —
including across sheets — so joins between sheets keep working.

### Clean up a file

Every problem found becomes a ticked fix card with a before → after sample:
junk rows above the real header, summary/footnote rows at the bottom, blank
rows and columns, exact duplicates, stray and non-breaking whitespace,
`N/A`/`NULL`/`--` markers, numbers stored as text (`$1,234.56` → `1234.56`,
`(2,500)` → `-2500`), mixed date formats normalized to `YYYY-MM-DD`, and cells
that would run as Excel formulas.

Untick anything you disagree with — the preview updates live — then download.
Detection is deliberately conservative: sheets with fewer than three populated
columns are left alone rather than guessed at, and ambiguous dates are read as
US month/day (the fix card says so, so you can untick it).

### Standardize

*Make a template*: drop in a file that already has the layout you want. Its
column names, order, and types (text / dates / numbers) are saved as a small
portable `template.json` — no cell data. Columns that repeat a short list of
values (a status, a category) also remember that list. Commit the template to
a repo or share it as your team's standard.

*Apply a template*: load a `template.json`, drop in a file from any system, and
review the proposed mapping. Columns are auto-matched by normalized names, a
synonym table (`DOB` = `Date of Birth` = `BirthDate`), shared tokens (`ID` →
`student_id`), and fuzzy matching for typos. Then:

- Template columns with no source come through empty, with a visible warning.
- Extra source columns are dropped unless you tick *keep it*.
- Values are coerced to the template's types; anything that doesn't fit is left
  intact and counted in a warning, never silently blanked.
- Spelling variants of remembered values are tidied up (`ACTIVE`, ` Inactive `,
  `In-Active` → `active` / `inactive`). Values that don't match are **never
  guessed** — `active` and `inactive` look similar but mean opposites. They are
  listed for you to map by hand, or left alone.

### Restore real values

Load the `mapping.json` from your redaction run, paste the AI's answer, and
every fake value becomes the original again. If nothing matches, it tells you —
usually a sign the key is from a different run.

## Limits — read before trusting it

- **Whole columns only.** Personal details written inside free text ("Spoke
  with Sarah's mother…") are **not** detected. Remove those columns if unsure.
- Redacted values are random fakes, not anonymization with formal guarantees.
  Rare combinations of the columns you *keep* (age + zip + diagnosis, say) can
  still identify someone. You remain responsible for what you share.
- Excel output is values-only: formulas and cell formatting are not preserved
  (sheets, columns, and rows are).
- Each run generates a fresh key file; there is no cross-file or cross-run
  consistency.
- Standardize works one sheet at a time (pick the sheet with the tabs).

## Tested against real federal data

The parser is exercised against public bulk datasets, including CDC NNDSS
(101 MB) and provisional COVID-19 deaths, Census county population estimates
(Latin-1 encoded) and state XLSX tables, the FEC candidate master
(pipe-delimited, no header row), FEMA disaster declarations, IRS migration
data, and Treasury debt data. All parse, redact, and round-trip cleanly.

## Development

```bash
pip install -e ".[dev]"
pytest
```

The engine (`app/engine/`) is pure Python; the FastAPI layer (`app/main.py`)
and the static page are thin wrappers over it. Tests are written first; please
keep it that way.

## Roadmap

- Detecting personal details inside free-text cells (Microsoft Presidio)
- Date shifting that preserves intervals between dates
- Command-line mode and saved redaction profiles
- Excel formatting preservation

## License

MIT
