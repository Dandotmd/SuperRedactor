"""Generate realistic fake replacement values, unique within a generator."""

import random
import string

from faker import Faker


def _format_preserving(real: str, rng: random.Random) -> str:
    out = []
    for ch in real:
        if ch.isdigit():
            out.append(rng.choice(string.digits))
        elif ch.isupper():
            out.append(rng.choice(string.ascii_uppercase))
        elif ch.islower():
            out.append(rng.choice(string.ascii_lowercase))
        else:
            out.append(ch)
    return "".join(out)


def _number(real: str, rng: random.Random) -> str:
    out = []
    first_digit = True
    for ch in real:
        if ch.isdigit():
            out.append(rng.choice("123456789" if first_digit else string.digits))
            first_digit = False
        else:
            out.append(ch)
    return "".join(out)


# In an identifier or a number, case is part of the value: 'aB3xK9' and
# 'Ab3Xk9' are two different records. In a name it is not.
CASE_SENSITIVE_TYPES = frozenset({"format_preserving", "number"})


def normalize_value(value: str, col_type: str | None = None) -> str:
    """The form used when deciding whether two values are 'the same real
    value'. Padding never makes a different value; capitalisation does for
    identifiers but not for names."""
    collapsed = " ".join(value.split())
    if col_type in CASE_SENSITIVE_TYPES:
        return collapsed
    # lower(), not casefold(): casefold folds ß to ss, merging "Straße"
    # and "Strasse" into one person and leaving one of them unrecoverable.
    return collapsed.lower()


class FakeGenerator:
    """Produces fake values for one column.

    Two guarantees matter more than realism:

    * a fake is never any real value from the file — otherwise a "redacted"
      roster still contains real people's names, just on the wrong rows;
    * a fake is never issued twice — otherwise one fake stands for two real
      values and restoring the originals silently returns the wrong one.

    `issued` and `forbidden` are shared across every generator in a run so
    the guarantees hold between columns, not just within one.
    """

    def __init__(
        self,
        col_type: str,
        seed: int | None = None,
        issued: set[str] | None = None,
        forbidden: set[str] | None = None,
    ):
        if col_type not in REDACTION_TYPES:
            raise ValueError(f"Unknown redaction type: {col_type}")
        self.col_type = col_type
        self._faker = Faker()
        self._rng = random.Random(seed)
        if seed is not None:
            self._faker.seed_instance(seed)
        self._issued: set[str] = issued if issued is not None else set()
        self._forbidden: set[str] = forbidden if forbidden is not None else set()
        # Whether the most recent call had to settle for a value it would
        # rather have avoided. Per call, not sticky: one crowded column must
        # not make every later column of the same type look crowded too.
        self.last_exhausted = False

    def _candidate(self, real: str) -> str:
        f, rng = self._faker, self._rng
        match self.col_type:
            case "person_name":
                return f.name()
            case "first_name":
                return f.first_name()
            case "last_name":
                return f.last_name()
            case "email":
                return f.email()
            case "phone":
                return f.numerify("(###) ###-####")
            case "ssn":
                return f.ssn()
            case "address":
                return f.street_address()
            case "city":
                return f.city()
            case "date":
                return f.date()
            case "number":
                return _number(real, rng)
            case "format_preserving":
                return _format_preserving(real, rng)
            case "custom_word":
                return f.word()
        raise AssertionError("unreachable")

    def next(self, real: str) -> str:
        self.last_exhausted = False
        if self.col_type in ("format_preserving", "number") and not any(
            c.isalnum() for c in real
        ):
            # Nothing to hide in "-" or " ": scrambling it would only produce
            # noise that no longer looks like the original column.
            return real

        for _ in range(120):
            fake = self._candidate(real)
            key = normalize_value(fake, self.col_type)
            if fake != real and key not in self._issued and key not in self._forbidden:
                self._issued.add(key)
                return fake

        # The pool can be genuinely smaller than the data — 26 single-letter
        # grade codes have no 27th possibility. Keep the column's shape and
        # let the caller warn that it cannot be hidden.
        for _ in range(120):
            fake = self._candidate(real)
            key = normalize_value(fake, self.col_type)
            if fake != real and key not in self._issued:
                self.last_exhausted = True
                self._issued.add(key)
                return fake

        base = self._candidate(real)
        n = 2
        while (
            normalize_value(f"{base} {n}", self.col_type) in self._issued
            or f"{base} {n}" == real
        ):
            n += 1
        fake = f"{base} {n}"
        self.last_exhausted = True
        self._issued.add(normalize_value(fake, self.col_type))
        return fake


REDACTION_TYPES: dict[str, str] = {
    "person_name": "Full name",
    "first_name": "First name",
    "last_name": "Last name",
    "email": "Email",
    "phone": "Phone",
    "ssn": "SSN",
    "address": "Street address",
    "city": "City",
    "date": "Date",
    "number": "Number (same size, e.g. 4 digits)",
    "format_preserving": "ID or code (keeps the same shape)",
    "custom_word": "A made-up word",
}
