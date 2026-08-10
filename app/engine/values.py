"""Reading what a cell actually means: numbers dressed up as text, and
dates written a dozen different ways.

Shared by the cleaners (which report and fix) and by standardize (which
coerces to a template's types), so both agree on what a number or a date
is.
"""

import re
from datetime import datetime

PLAIN_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")
# $1,234.56 · (2,500) · 45% · -$1,000.50 · $-40.00
#
# Commas must group three digits at a time. "2,5" is two and a half in most
# of the world, and stripping its comma would silently multiply it by ten,
# so a lone comma before one or two digits is not treated as a number here.
DECORATED_NUMBER = re.compile(
    r"^\(?-?\$?\s?-?\d{1,3}(,\d{3})*(\.\d+)?\)?%?$|^\(?-?\$?\s?-?\d+(\.\d+)?\)?%?$"
)

DATE_FORMATS = (
    "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%m-%d-%Y",
    "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%d-%b-%Y",
)

# Cheap gate before the expensive strptime attempts: a date always starts
# with a digit or a letter and is short. Without this, every cell in every
# column pays ten failed parses, which dominated runtime on large files.
_MAYBE_DATE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ,/-]{5,29}$")
_DATE_CACHE: dict[str, datetime | None] = {}
_DATE_CACHE_LIMIT = 100_000

# 05/06/2024 is the 5th of June in most of the world and the 6th of May in
# the US. Both readings parse, so the only honest thing is to say which one
# was used.
_AMBIGUOUS_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/\d{2,4}$")


def strip_number(value: str) -> str:
    """'$1,234.56' -> '1234.56', '(2,500)' -> '-2500', '-$1,000.50' -> '-1000.50'."""
    v = value.strip()
    # The sign can sit either side of the currency symbol: -$40 and $-40
    first_digit = next((i for i, c in enumerate(v) if c.isdigit()), len(v))
    negative = "-" in v[:first_digit] or (v.startswith("(") and v.endswith(")"))
    v = v.replace("$", "").replace(",", "").replace(" ", "")
    if v.endswith("%"):
        v = v[:-1]
    v = v.strip("()-")
    return "-" + v if negative and v else v


def parse_date(value: str) -> datetime | None:
    v = value.strip()
    if not _MAYBE_DATE.match(v):
        return None
    cached = _DATE_CACHE.get(v, False)
    if cached is not False:
        return cached
    parsed = None
    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(v, fmt)
            break
        except ValueError:
            continue
    if len(_DATE_CACHE) < _DATE_CACHE_LIMIT:
        _DATE_CACHE[v] = parsed
    return parsed


def is_ambiguous_date(value: str) -> bool:
    """True when the same text is a valid date under both day/month and
    month/day, so the reading has to be disclosed."""
    match = _AMBIGUOUS_DATE.match(value.strip())
    if not match:
        return False
    first, second = int(match.group(1)), int(match.group(2))
    return first <= 12 and second <= 12 and first != second
