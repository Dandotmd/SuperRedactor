"""Value-level safety rules shared by the cleaners and the writers."""

import re

# A leading "=" is a formula in every spreadsheet program and never
# legitimate data, so it is enough on its own.
#
# A leading +, - or @ is different: it opens most real phone numbers
# (+44 20 7946 0000), negative money (-$40.00), scientific notation
# (-1.5e10) and social handles (@example.com). Flagging all of those
# rewrote ordinary columns on every download. What turns them into an
# attack is the syntax that follows — a function call, a DDE pipe, or a
# sheet reference — so that is what is looked for.
_EXECUTABLE_SYNTAX = re.compile(r"[(|!]")
_HAS_LETTER = re.compile(r"[A-Za-z]")


def is_formula_risk(value: str) -> bool:
    """True when a spreadsheet would run this cell instead of showing it.

    Aimed at command execution — DDE payloads like `=cmd|'/c calc'!A1`,
    `@SUM(...)`, `+cmd|calc` — rather than at every value that happens to
    start with punctuation.
    """
    if not value:
        return False
    text = value.lstrip("\t\r\n")
    if not text:
        return False
    if text[0] == "=":
        return True
    if text[0] in "+-@":
        rest = text[1:]
        return bool(_EXECUTABLE_SYNTAX.search(rest) and _HAS_LETTER.search(rest))
    return False


def neutralize(value: str) -> str:
    """Render a formula-like value inert while keeping it readable."""
    return "'" + value if is_formula_risk(value) else value
