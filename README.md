# PII Redactor

A small local web app that scrubs sensitive columns from CSV and Excel files
before you share them with AI tools — and translates the AI's answers back
afterward.

You pick the columns; each one is replaced with **realistic fake data** (fake
names stay names, fake SSNs look like SSNs, IDs keep their exact format), so
the file keeps its structure and anything an AI builds against it works
unchanged on the real data. A `mapping.json` produced with each run lets you
swap the fake values back to the originals — locally, whenever you need to.

## Why

If you work with regulated or confidential data (FERPA, HIPAA, plain
"don't leak the customer list"), you can't paste real exports into an AI tool.
But you still want AI help building dashboards, scripts, and analyses around
that data. Redact first, build against the fakes, de-redact the results.

## Privacy guarantees

- **Everything runs on your machine.** The server binds to `127.0.0.1` only.
- **No outbound requests, ever.** No telemetry, no CDN assets, no font
  downloads — the page is fully self-contained.
- **Nothing touches disk on the server side.** Uploaded files live in process
  memory and are gone when you stop the server.
- **The mapping stays with you.** `mapping.json` is the only way back from
  fake to real values. Keep it local; treat it like the data itself.

## Install & run

Requires Python 3.10+.

```bash
git clone <this repo>
cd pii-redactor
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
pii-redactor
```

Your browser opens at `http://127.0.0.1:8321`.

## Using it

1. **Drop in a `.csv` or `.xlsx`** (all sheets are loaded).
2. **Review the columns.** Likely PII columns are pre-marked from their
   header names — always check every column yourself; the suggestions are
   heuristics, not a guarantee.
3. Set each column to **Keep**, **Redact as** a type (name, email, phone,
   SSN, address, date, number, format-preserving ID, …), or **Drop**.
   Marked columns preview as black redaction bars.
4. **Download the ZIP**: the redacted file plus `grades.mapping.json`.
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
  (sheets, columns, and rows are).
- Each run generates a fresh mapping; there is no cross-file or cross-run
  consistency.

## Development

```bash
pip install -e ".[dev]"
pytest
```

The redaction engine (`app/engine/`) is pure Python with no web dependencies;
the FastAPI layer (`app/main.py`) and the static page are thin wrappers over it.

## Roadmap

- Free-text PII scanning inside cells (Microsoft Presidio)
- Date shifting that preserves intervals
- CLI mode and saved redaction profiles
- Excel formatting preservation

## License

MIT
