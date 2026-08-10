"""Suggest a redaction type from a column header name. Heuristic only —
the user always confirms in the UI before anything is redacted."""

import re


# A heading that names a person's role usually holds that person's name.
_PERSON_ROLES = {
    "patient", "student", "guardian", "employee", "client", "parent",
    "teacher", "contact", "member", "customer", "staff", "resident",
    "provider", "caregiver", "applicant", "participant",
}


# Words that can sit beside a role without changing what the column holds.
_ROLE_QUALIFIERS = {
    "emergency", "primary", "secondary", "alternate", "legal", "main",
    "next", "of", "kin", "the", "full", "preferred", "current", "former",
}


def _tokens(header: str) -> list[str]:
    # split camelCase, then non-alphanumerics, then lowercase
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", header)
    return [t for t in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if t]


def suggest_type(header: str) -> str | None:
    ordered = _tokens(header)
    if not ordered:
        return None
    joined = " ".join(ordered)  # phrases need the original order
    tokens = set(ordered)

    if "ssn" in tokens or "social security" in joined:
        return "ssn"
    if "email" in tokens or "mail" in tokens:
        return "email"
    if tokens & {"phone", "mobile", "fax", "cell", "telephone", "tel"}:
        return "phone"
    if "dob" in tokens or "birth" in tokens or "date" in tokens:
        return "date"
    if "address" in tokens or "street" in tokens:
        return "address"
    if "city" in tokens:
        return "city"
    if "zip" in tokens or "postal" in tokens:
        return "format_preserving"
    if ("first" in tokens and "name" in tokens) or joined in ("first", "fname", "forename"):
        return "first_name"
    if (
        ("last" in tokens and "name" in tokens)
        or "surname" in tokens
        or joined in ("last", "lname")
    ):
        return "last_name"
    if "name" in tokens:
        return "person_name"
    if "id" in tokens or "mrn" in tokens or "identifier" in tokens:
        return "format_preserving"
    # Checked last, so "Student ID" is an identifier while a bare
    # "Student" column holds the student's name. Every remaining word must
    # be part of naming the person — "Emergency Contact" is a name,
    # "Employee Number" and "Teacher Rating" are not.
    if tokens & _PERSON_ROLES and tokens <= _PERSON_ROLES | _ROLE_QUALIFIERS:
        return "person_name"
    return None
