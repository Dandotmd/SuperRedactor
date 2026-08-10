"""Value-level safety rules shared by the cleaners and the writers."""

import re

_PLAIN_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")


def is_formula_risk(value: str) -> bool:
    """True when a spreadsheet would execute this cell instead of showing it.

    Excel, LibreOffice and Sheets all treat a leading =, +, - or @ as the
    start of a formula, which is how a hostile export turns into a DDE or
    HYPERLINK payload on the next person's machine. Negative numbers are
    excluded — they are the common, harmless case.
    """
    if not value:
        return False
    if value[0] in "=@\t\r":
        return True
    if value[0] in "+-":
        return not _PLAIN_NUMBER.match(value.strip())
    return False


def neutralize(value: str) -> str:
    """Render a formula-like value inert while keeping it readable."""
    return "'" + value if is_formula_risk(value) else value
