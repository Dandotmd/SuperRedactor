"""Value-level safety rules shared by the cleaners and the writers."""

import re

# A leading "=" is a formula in every spreadsheet program and never
# legitimate data, so it is enough on its own.
#
# A leading +, - or @ is different: it opens real phone numbers
# (+44 20 7946 0000), negative money (-$40.00), scientific notation
# (-1.5e10), social handles (@example.com) and no end of note-column prose
# ("-Smith (deceased)", "- see notes (p. 3)"). Flagging all of those
# rewrote ordinary columns on every download. What turns them into an
# attack is specific syntax:
#   |          a DDE pipe, as in cmd|'/c calc'
#   NAME(      a function call, letters running straight into a bracket
#   !A1        a sheet or cell reference
# Prose has spaces where formulas do not, which is what separates
# "@SUM(A1)" from "@johndoe (Twitter)".
_EXECUTABLE_SYNTAX = re.compile(r"\||[A-Za-z]\(|![A-Za-z$]")

# Every kind of blank a spreadsheet ignores in front of a formula,
# including the invisible ones a hostile file would use to slip past.
_LEADING_BLANKS = "\t\r\n\v\f         "
_LEADING_BLANKS += "     ​  　﻿"


def is_formula_risk(value: str) -> bool:
    """True when a spreadsheet would run this cell instead of showing it.

    Aimed at command execution — DDE payloads like `=cmd|'/c calc'!A1`,
    `@SUM(...)`, `+cmd|calc` — rather than at every value that happens to
    start with punctuation.
    """
    if not value:
        return False
    text = value.lstrip(_LEADING_BLANKS)
    if not text:
        return False
    if text[0] == "=":
        return True
    if text[0] in "+-@":
        return bool(_EXECUTABLE_SYNTAX.search(text[1:]))
    return False


def neutralize(value: str) -> str:
    """Render a formula-like value inert while keeping it readable."""
    return "'" + value if is_formula_risk(value) else value
