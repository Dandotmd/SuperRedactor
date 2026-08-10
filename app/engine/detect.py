"""Suggest a redaction type from a column header name. Heuristic only —
the user always confirms in the UI before anything is redacted."""

import re


def _tokens(header: str) -> list[str]:
    # split camelCase, then non-alphanumerics, then lowercase
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", header)
    return [t for t in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if t]


def suggest_type(header: str) -> str | None:
    tokens = _tokens(header)
    if not tokens:
        return None
    joined = " ".join(tokens)

    if "ssn" in tokens or "social security" in joined:
        return "ssn"
    if "email" in tokens or "mail" in tokens:
        return "email"
    if "phone" in tokens or "mobile" in tokens or "fax" in tokens:
        return "phone"
    if "dob" in tokens or "birth" in tokens or "date" in tokens:
        return "date"
    if "address" in tokens or "street" in tokens:
        return "address"
    if "city" in tokens:
        return "city"
    if "zip" in tokens or "postal" in tokens:
        return "format_preserving"
    if "first" in tokens and "name" in tokens:
        return "first_name"
    if "last" in tokens and "name" in tokens or "surname" in tokens:
        return "last_name"
    if "name" in tokens:
        return "person_name"
    if "id" in tokens or "mrn" in tokens or "identifier" in tokens:
        return "format_preserving"
    return None
