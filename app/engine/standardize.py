"""Map arbitrarily-shaped sheets onto a saved template: rename and reorder
columns, coerce types, and surface what didn't fit as warnings.

Templates are portable JSON (no cell data): column names, order, and
expected types. `version` lets the format grow (e.g. value vocabularies)
without breaking older files.
"""

import difflib
import re

from app.engine.cleaners import _DECORATED_NUMBER, _PLAIN_NUMBER, _parse_date, _strip_number
from app.engine.readers import Sheet

TEMPLATE_VERSION = 1

# Groups of header spellings that mean the same thing (normalized form).
_SYNONYM_GROUPS = [
    {"dob", "dateofbirth", "birthdate", "birthday", "born"},
    {"ssn", "socialsecuritynumber", "socialsecurity"},
    {"phone", "phonenumber", "telephone", "tel", "mobile", "cell"},
    {"email", "emailaddress", "mail", "e mail"},
    {"zip", "zipcode", "postalcode", "postcode"},
    {"firstname", "fname", "givenname"},
    {"lastname", "lname", "surname", "familyname"},
    {"name", "fullname"},
    {"id", "identifier", "recordid"},
    {"address", "streetaddress", "street"},
]
_SYNONYM_KEY = {
    variant: min(group) for group in _SYNONYM_GROUPS for variant in group
}


def _norm(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", header.lower())


def _synonym_key(header: str) -> str:
    n = _norm(header)
    return _SYNONYM_KEY.get(n, n)


def _tokens(header: str) -> set[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", header)
    return {
        _SYNONYM_KEY.get(t, t)
        for t in re.split(r"[^A-Za-z0-9]+", spaced.lower())
        if t
    }


def _guess_type(values: list[str]) -> str:
    filled = [v for v in values if v.strip()]
    if len(filled) >= 3:
        if sum(1 for v in filled if _parse_date(v)) / len(filled) >= 0.8:
            return "date"
    if len(filled) >= 2:
        numeric = sum(
            1 for v in filled
            if _PLAIN_NUMBER.match(v.strip()) or _DECORATED_NUMBER.match(v.strip())
        )
        if numeric / len(filled) >= 0.8:
            return "number"
    return "text"


def make_template(sheet: Sheet, name: str) -> dict:
    return {
        "tool": "superredactor",
        "kind": "template",
        "version": TEMPLATE_VERSION,
        "name": name,
        "columns": [
            {
                "name": header,
                "type": _guess_type([row[i] for row in sheet.rows]),
            }
            for i, header in enumerate(sheet.headers)
        ],
    }


def match_columns(template_cols: list[str], headers: list[str]) -> dict[str, str | None]:
    """Propose a source header for each template column. Exact normalized
    match first, then synonyms, then closest fuzzy match; each source
    header is used at most once."""
    mapping: dict[str, str | None] = {c: None for c in template_cols}
    available = list(headers)

    def take(template_col: str, header: str):
        mapping[template_col] = header
        available.remove(header)

    for col in template_cols:
        for header in available:
            if _norm(header) == _norm(col):
                take(col, header)
                break

    for col in template_cols:
        if mapping[col] is not None:
            continue
        for header in available:
            if _synonym_key(header) == _synonym_key(col):
                take(col, header)
                break

    # Shared tokens: "Student Name" ~ "name", "ID" ~ "student_id"
    for col in template_cols:
        if mapping[col] is not None:
            continue
        col_tokens = _tokens(col)
        scored = []
        for h in available:
            h_tokens = _tokens(h)
            overlap = col_tokens & h_tokens
            if overlap:
                scored.append((len(overlap) / len(col_tokens | h_tokens), h))
        if scored and max(scored)[0] >= 0.4:
            take(col, max(scored)[1])

    # Character-level fuzz for typos ("Amout" ~ "amount")
    for col in template_cols:
        if mapping[col] is not None:
            continue
        scored = [
            (difflib.SequenceMatcher(None, _norm(col), _norm(h)).ratio(), h)
            for h in available
        ]
        scored = [(score, h) for score, h in scored if score >= 0.8]
        if scored:
            take(col, max(scored)[1])

    return mapping


def _coerce(value: str, col_type: str) -> str | None:
    """Returns the coerced value, or None when the cell can't be coerced."""
    v = value.strip()
    if not v:
        return value
    if col_type == "date":
        d = _parse_date(v)
        return d.strftime("%Y-%m-%d") if d else None
    if col_type == "number":
        if _PLAIN_NUMBER.match(v):
            return v
        if _DECORATED_NUMBER.match(v):
            return _strip_number(v)
        return None
    return value


def apply_template(
    sheet: Sheet,
    template: dict,
    mapping: dict[str, str | None],
    keep_extras: list[str],
) -> tuple[Sheet, list[str]]:
    warnings: list[str] = []
    src_idx = {h: i for i, h in enumerate(sheet.headers)}

    out_headers: list[str] = []
    columns: list[tuple[int | None, str]] = []  # (source index, type)
    for col in template["columns"]:
        out_headers.append(col["name"])
        source = mapping.get(col["name"])
        if source is None:
            warnings.append(f"No source column for '{col['name']}' — filled with empty cells")
            columns.append((None, col["type"]))
        else:
            columns.append((src_idx[source], col["type"]))

    for extra in keep_extras:
        out_headers.append(extra)
        columns.append((src_idx[extra], "text"))

    failed: dict[str, int] = {}
    rows: list[list[str]] = []
    for row in sheet.rows:
        out_row: list[str] = []
        for (idx, col_type), name in zip(columns, out_headers):
            if idx is None:
                out_row.append("")
                continue
            coerced = _coerce(row[idx], col_type)
            if coerced is None:
                failed[name] = failed.get(name, 0) + 1
                out_row.append(row[idx])
            else:
                out_row.append(coerced)
        rows.append(out_row)

    for name, count in failed.items():
        warnings.append(
            f"'{name}': {count} cell(s) did not fit the expected type and were left as-is"
        )

    return Sheet(name=sheet.name, headers=out_headers, rows=rows), warnings
