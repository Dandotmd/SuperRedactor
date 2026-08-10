"""Map arbitrarily-shaped sheets onto a saved template: rename and reorder
columns, coerce types, and surface what didn't fit as warnings.

Templates are portable JSON (no cell data): column names, order, and
expected types. `version` lets the format grow (e.g. value vocabularies)
without breaking older files.
"""

import difflib
import re
from dataclasses import dataclass, field

from app.engine.detect import suggest_type
from app.engine.readers import Sheet
from app.engine.values import (
    DECORATED_NUMBER,
    PLAIN_NUMBER,
    is_ambiguous_date,
    parse_date,
    strip_number,
)

TEMPLATE_VERSION = 1

# A column is treated as categorical (worth capturing a vocabulary for) when
# it repeats a small set of values — e.g. status codes, not names.
MAX_VOCABULARY = 12
MAX_DISTINCT_RATIO = 0.5

# Templates get committed to repositories and emailed around, and the
# values they remember are copied out of a real file. Columns holding
# health or free-text information never remember anything, on top of the
# name/address columns the PII detector already recognises.
_NEVER_REMEMBERED = {
    "diagnosis", "diagnoses", "condition", "conditions", "medication",
    "medications", "med", "meds", "prescription", "allergy", "allergies",
    "treatment", "procedure", "symptom", "symptoms", "disability",
    "notes", "note", "comment", "comments", "remarks", "description",
    "reason", "complaint", "religion", "ethnicity", "race", "gender",
    "sex", "orientation", "income", "salary", "wage",
}


@dataclass
class StandardizeResult:
    sheet: Sheet
    warnings: list[str] = field(default_factory=list)
    # column name -> values that matched no vocabulary entry, for the UI to
    # offer manual mapping. Never guessed at automatically.
    unmatched: dict[str, list[str]] = field(default_factory=dict)

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
        if sum(1 for v in filled if parse_date(v)) / len(filled) >= 0.8:
            return "date"
    if len(filled) >= 2:
        numeric = sum(
            1 for v in filled
            if PLAIN_NUMBER.match(v.strip()) or DECORATED_NUMBER.match(v.strip())
        )
        if numeric / len(filled) >= 0.8:
            return "number"
    return "text"


def _guess_vocabulary(values: list[str]) -> list[str] | None:
    filled = [v.strip() for v in values if v.strip()]
    if len(filled) < 3:
        return None
    distinct = sorted(set(filled))
    if len(distinct) > MAX_VOCABULARY:
        return None
    if len(distinct) / len(filled) > MAX_DISTINCT_RATIO:
        return None
    return distinct


def make_template(sheet: Sheet, name: str) -> dict:
    """Describe a sheet's shape so other files can be reshaped to match.

    Columns that repeat a short list of values also remember that list, so
    spellings can be tidied later. Those values are real data, and templates
    get shared — so a column whose heading suggests personal information
    never remembers anything, and the caller is told which columns do.
    """
    columns = []
    carries_values = []
    for i, header in enumerate(sheet.headers):
        values = [row[i] for row in sheet.rows]
        column = {"name": header, "type": _guess_type(values)}
        sensitive = bool(_tokens(header) & _NEVER_REMEMBERED)
        if column["type"] == "text" and suggest_type(header) is None and not sensitive:
            vocabulary = _guess_vocabulary(values)
            if vocabulary:
                column["values"] = vocabulary
                carries_values.append(header)
        columns.append(column)
    return {
        "tool": "superredactor",
        "kind": "template",
        "version": TEMPLATE_VERSION,
        "name": name,
        "columns": columns,
        "columns_with_values": carries_values,
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


def suggest_sources(
    template_cols: list[str], headers: list[str], mapping: dict[str, str | None]
) -> dict[str, str]:
    """For template columns nothing matched, the closest leftover column.

    Offered as "did you mean…?" rather than applied: a wrong auto-match
    silently moves data into the wrong column, while a wrong suggestion
    costs one glance.
    """
    used = {v for v in mapping.values() if v}
    spare = [h for h in headers if h not in used]
    suggestions: dict[str, str] = {}
    for col in template_cols:
        if mapping.get(col) is not None or not spare:
            continue
        col_tokens = _tokens(col)
        scored = []
        for header in spare:
            shared = len(col_tokens & _tokens(header)) / max(
                1, len(col_tokens | _tokens(header))
            )
            close = difflib.SequenceMatcher(None, _norm(col), _norm(header)).ratio()
            scored.append((max(shared, close), header))
        score, header = max(scored)
        if score >= 0.3:
            suggestions[col] = header
            spare.remove(header)
    return suggestions


def _coerce(value: str, col_type: str) -> str | None:
    """Returns the coerced value, or None when the cell can't be coerced."""
    v = value.strip()
    if not v:
        return value
    if col_type == "date":
        d = parse_date(v)
        return d.strftime("%Y-%m-%d") if d else None
    if col_type == "number":
        if PLAIN_NUMBER.match(v):
            return v
        if DECORATED_NUMBER.match(v):
            return strip_number(v)
        return None
    return value


def _vocabulary_lookup(col: dict) -> dict[str, str]:
    """Normalized spelling -> canonical value. Only exact-after-normalization
    matches are used; near-miss values are never guessed at, because
    'active' and 'inactive' are textually similar but opposite in meaning."""
    lookup = {_norm(v): v for v in col.get("values") or [] if isinstance(v, str)}
    for alias, canonical in (col.get("aliases") or {}).items():
        if isinstance(alias, str) and isinstance(canonical, str):
            lookup[_norm(alias)] = canonical
    return lookup


def apply_template(
    sheet: Sheet,
    template: dict,
    mapping: dict[str, str | None],
    keep_extras: list[str],
) -> StandardizeResult:
    warnings: list[str] = []
    src_idx = {h: i for i, h in enumerate(sheet.headers)}

    out_headers: list[str] = []
    columns: list[tuple[int | None, str, dict[str, str]]] = []
    for col in template["columns"]:
        out_headers.append(col["name"])
        vocabulary = _vocabulary_lookup(col)
        source = mapping.get(col["name"])
        if source is None:
            warnings.append(f"No source column for '{col['name']}' — filled with empty cells")
            columns.append((None, col["type"], vocabulary))
        else:
            columns.append((src_idx[source], col["type"], vocabulary))

    for extra in keep_extras:
        out_headers.append(extra)
        columns.append((src_idx[extra], "text", {}))

    failed: dict[str, int] = {}
    ambiguous: dict[str, int] = {}
    unmatched: dict[str, list[str]] = {}
    rows: list[list[str]] = []
    for row in sheet.rows:
        out_row: list[str] = []
        for (idx, col_type, vocabulary), name in zip(columns, out_headers):
            if idx is None:
                out_row.append("")
                continue
            value = row[idx]
            if vocabulary and value.strip():
                canonical = vocabulary.get(_norm(value))
                if canonical is not None:
                    out_row.append(canonical)
                    continue
                seen = unmatched.setdefault(name, [])
                if value not in seen:
                    seen.append(value)
                out_row.append(value)
                continue
            coerced = _coerce(value, col_type)
            if coerced is None:
                failed[name] = failed.get(name, 0) + 1
                out_row.append(value)
            else:
                if col_type == "date" and is_ambiguous_date(value):
                    ambiguous[name] = ambiguous.get(name, 0) + 1
                out_row.append(coerced)
        rows.append(out_row)

    for name, count in ambiguous.items():
        warnings.append(
            f"'{name}': {count} date(s) could be read two ways (is 05/06 the 5th "
            f"of June or the 6th of May?). They were read as month/day, the US "
            f"convention. Check them if your data is day/month."
        )
    for name, count in failed.items():
        warnings.append(
            f"'{name}': {count} cell(s) did not fit the expected type and were left as-is"
        )
    for name, values in unmatched.items():
        shown = ", ".join(repr(v) for v in values[:5])
        more = f" and {len(values) - 5} more" if len(values) > 5 else ""
        warnings.append(
            f"'{name}': {len(values)} value(s) are not in the template's list — "
            f"{shown}{more}. Left unchanged; map them below if they belong."
        )

    return StandardizeResult(
        sheet=Sheet(name=sheet.name, headers=out_headers, rows=rows),
        warnings=warnings,
        unmatched=unmatched,
    )
