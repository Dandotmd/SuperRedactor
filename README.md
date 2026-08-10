# SuperRedactor

A local web app that scrubs sensitive columns from CSV and Excel files before
you share them with AI tools — and translates the AI's answers back afterward.

You pick the columns; each one is replaced with **realistic fake data** (fake
names stay names, fake SSNs look like SSNs, IDs keep their exact format), so
the file keeps its structure and anything an AI builds against it works
unchanged on the real data. A `mapping.json` produced with each run lets you
swap the fake values back to the originals — locally, whenever you need to.

**Everything runs on your machine. Nothing is uploaded anywhere, ever.**

## Why

If you work with regulated or confidential data (FERPA, HIPAA, PII covered by
the Privacy Act, or plain "don't leak the customer list"), you can't paste
real exports into an AI tool. But you still want AI help building dashboards,
scripts, and analyses around that data. Redact first, build against the
fakes, de-redact the results.

## Privacy & security posture

Designed so that a security reviewer can verify every claim by reading a
small amount of code:

- **Localhost only.** The server binds to `127.0.0.1:8321` and is unreachable
  from the network.
- **Zero outbound requests.** No telemetry, no update checks, no CDN scripts,
  no font downloads. The web page is fully self-contained; the codebase
  contains no HTTP client.
- **No server-side persistence.** Uploaded files live in process memory only
  and vanish when the server stops. Nothing is written to disk except the
  ZIP you explicitly download.
- **Small, auditable dependency list**: FastAPI, uvicorn, python-multipart,
  openpyxl, Faker. The redaction engine itself (`app/engine/`) is pure
  Python with no web dependencies.
- **The mapping is the key.** `mapping.json` is the only path from fake
  values back to real ones. Treat it with the same care as the source data;
  never share it or upload it.

## Install & run (standard machine)

Requires Python 3.10 or newer. No admin rights needed.

```bash
git clone https://github.com/Dandotmd/SuperRedactor.git
cd SuperRedactor
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
superredactor
```

Your browser opens at `http://127.0.0.1:8321`. Stop the server with `Ctrl+C`;
everything it held in memory is gone.

Prefer not to install at all? `pip install -e .` once, or run directly:

```bash
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8321
```

## Install on locked-down / government computers

You often can't run arbitrary installers or reach the open internet from a
work machine. Options, in order of preference:

**1. No git? Download a ZIP.**
On GitHub, *Code → Download ZIP*, transfer it by your approved method, unzip,
and follow the normal steps — git is not required to run the tool.

**2. Python without admin rights.**
The python.org installer supports a per-user install (no elevation), or use
whatever your agency's software center provides. Any CPython 3.10+ works.
On Windows, if `python3` isn't found, try `py -3` or `python`.

**3. pip behind a corporate proxy / TLS inspection.**
If `pip install` fails with certificate errors, your agency likely intercepts
TLS. Point pip at your organization's CA bundle (ask IT for the `.pem`):

```bash
pip config set global.cert /path/to/agency-ca-bundle.pem
```

Set `HTTPS_PROXY` if your network requires it. Do **not** disable certificate
verification.

**4. Fully offline (air-gapped) install.**
On any internet-connected machine with the same OS/Python major version:

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
network code is the uvicorn server bound to `127.0.0.1`. Run `pytest` to see
the whole engine exercised. Your agency's rules for handling the *source*
data still apply to the machine you run this on and to `mapping.json`.

> SuperRedactor is an independent open-source tool. It is not produced or
> endorsed by any government agency. Redacting a file does not by itself
> make it releasable — follow your organization's data-handling policy.

## Using it

1. **Drop in a `.csv` or `.xlsx`** (all sheets are loaded). Delimiters
   (comma, pipe, tab, semicolon), Latin-1/Windows encodings, ragged rows,
   and headerless files (e.g. FEC bulk data) are handled automatically.
2. **Review the columns.** Likely PII columns are pre-marked from their
   header names — always check every column yourself; the suggestions are
   heuristics, not a guarantee.
3. Set each column to **Keep**, **Redact as** a type (name, email, phone,
   SSN, address, date, number, format-preserving ID, …), or **Drop**.
   Marked columns preview as black redaction bars.
4. **Download the ZIP**: the redacted file plus `<name>.mapping.json`.
5. Use the redacted file with your AI tool. When the AI's output mentions
   fake values, open the **De-redact** tab, load the mapping, paste the
   output, and get the real values back.

Consistency: within a run, the same real value always becomes the same fake
value — including across sheets — so joins between sheets keep working.

## Limits — read before trusting it

- **Whole columns only.** PII buried inside free-text cells ("Spoke with
  Sarah's mother…") is **not** detected. Drop those columns if in doubt.
- Redacted values are random fakes, not anonymization with formal guarantees.
  Rare combinations of the columns you *keep* (age + zip + diagnosis, say)
  can still identify someone. You remain responsible for what you share.
- Excel output is values-only: formulas and cell formatting are not preserved
  (sheets, columns, and rows are). Legacy `.xls` isn't supported — re-save
  as `.xlsx` or CSV first.
- Each run generates a fresh mapping; there is no cross-file or cross-run
  consistency.

## Tested against real federal data

The parser is exercised against public bulk datasets, including: CDC NNDSS
(101 MB) and provisional COVID-19 deaths, Census county population estimates
(Latin-1 encoded) and state XLSX tables (merged headers), FEC candidate
master (pipe-delimited, no header row), FEMA disaster declarations, IRS
migration data, and Treasury debt data. All parse, redact, and round-trip
cleanly.

## Development

```bash
pip install -e ".[dev]"
pytest
```

Engine (`app/engine/`) is pure Python; the FastAPI layer (`app/main.py`) and
the static page are thin wrappers over it. Tests are written first; PRs
should keep it that way.

## Roadmap

- Free-text PII scanning inside cells (Microsoft Presidio)
- Date shifting that preserves intervals
- CLI mode and saved redaction profiles
- Excel formatting preservation

## License

MIT
