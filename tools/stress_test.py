#!/usr/bin/env python3
"""Run every file in a directory through the full pipeline and report.

Used to check the parser against real-world spreadsheets — public federal
bulk data is a good source because it is large, inconsistently formatted,
and free to redistribute.

    python tools/stress_test.py ~/Downloads/testdata

Each file is parsed, analyzed for cleanup, cleaned, redacted (every column
the detector suggests), written back out, and re-parsed. Any exception, row
count change, or pathological runtime is reported.

Suggested corpus (download by hand; sizes as of 2026):
  Census county estimates (Latin-1, 1.7 MB)
    https://www2.census.gov/programs-surveys/popest/datasets/2020-2024/counties/totals/co-est2024-alldata.csv
  Census state totals (XLSX with merged title rows)
    https://www2.census.gov/programs-surveys/popest/tables/2020-2024/state/totals/NST-EST2024-POP.xlsx
  FEC candidate master (pipe-delimited, no header row) — cn.txt inside
    https://www.fec.gov/files/bulk-downloads/2024/cn24.zip
  FEMA disaster declarations (23 MB)
    https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries.csv
  CDC provisional COVID-19 deaths (24 MB)
    https://data.cdc.gov/api/views/9bhg-hcku/rows.csv?accessType=DOWNLOAD
  Treasury debt to the penny
    https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/debt_to_penny?format=csv

Rename FEC's cn.txt to cn.csv (the extension picks the parser; the
delimiter is sniffed).
"""

import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.engine.cleaners import clean
from app.engine.detect import suggest_type
from app.engine.leakcheck import find_leaks
from app.engine.readers import read_file
from app.engine.redactor import redact
from app.engine.writers import write_csv, write_xlsx

SLOW_SECONDS = 30


def check(path: Path) -> tuple[str, str]:
    started = time.time()
    sheets = read_file(path.name, path.read_bytes())
    rows_in = sum(len(s.rows) for s in sheets)

    cleaned, findings = clean(sheets, enabled=None)

    config = {}
    for sheet in sheets:
        columns = {h: t for h in sheet.headers if (t := suggest_type(h))}
        if columns:
            config[sheet.name] = columns
    redacted, mapping = redact(sheets, config)
    leaks = find_leaks(sheets, config)

    payload = (
        write_xlsx(redacted)
        if path.suffix.lower() in (".xlsx", ".xlsm")
        else write_csv(redacted[0])
    )
    reparsed = read_file("out" + path.suffix, payload)
    rows_out = sum(len(s.rows) for s in reparsed)

    elapsed = time.time() - started
    detail = (
        f"rows={rows_in} sheets={len(sheets)} "
        f"cleanup_findings={len(findings)} redacted_cols={sum(len(c) for c in config.values())} "
        f"leak_warnings={len(leaks)} {elapsed:.1f}s"
    )
    if rows_out != rows_in:
        return "ROW MISMATCH", f"{rows_in} in, {rows_out} out — {detail}"
    if elapsed > SLOW_SECONDS:
        return "SLOW", detail
    return "OK", detail


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    directory = Path(sys.argv[1]).expanduser()
    if not directory.is_dir():
        print(f"Not a directory: {directory}")
        return 2

    failures = 0
    for path in sorted(directory.iterdir()):
        if path.suffix.lower() not in (".csv", ".tsv", ".txt", ".xlsx", ".xlsm"):
            continue
        label = f"{path.name} ({path.stat().st_size // 1024} KB)"
        try:
            status, detail = check(path)
        except Exception:
            status = "FAIL"
            detail = traceback.format_exc().strip().splitlines()[-1]
        if status != "OK":
            failures += 1
        print(f"{status:14} {label}\n{'':14} {detail}")

    print(f"\n{failures} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
