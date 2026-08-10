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
        # True once the pool of possible fakes was too small to avoid reusing
        # a real value — the caller warns the user, because such a column
        # cannot actually be hidden.
        self.exhausted = False

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
        if self.col_type in ("format_preserving", "number") and not any(
            c.isalnum() for c in real
        ):
            # Nothing to hide in "-" or " ": scrambling it would only produce
            # noise that no longer looks like the original column.
            return real

        for _ in range(120):
            fake = self._candidate(real)
            if fake != real and fake not in self._issued and fake not in self._forbidden:
                self._issued.add(fake)
                return fake

        # The pool can be genuinely smaller than the data — 26 single-letter
        # grade codes have no 27th possibility. Keep the column's shape and
        # let the caller warn that it cannot be hidden.
        for _ in range(120):
            fake = self._candidate(real)
            if fake != real and fake not in self._issued:
                self.exhausted = True
                self._issued.add(fake)
                return fake

        base = self._candidate(real)
        n = 2
        while f"{base} {n}" in self._issued or f"{base} {n}" == real:
            n += 1
        fake = f"{base} {n}"
        self.exhausted = True
        self._issued.add(fake)
        return fake


# Roughly how many different values each generator can produce. Used to warn
# — before anything is downloaded — that a column has too few possibilities
# to actually hide anyone. Deliberately conservative.
_POOL_SIZES = {
    "person_name": 1_000_000,
    "first_name": 3_000,
    "last_name": 1_000,
    "email": 1_000_000,
    "phone": 10_000_000,
    "ssn": 1_000_000,
    "address": 1_000_000,
    "city": 1_000,
    "date": 10_000,
    "custom_word": 1_000,
}


def _shape_space(value: str) -> int:
    space = 1
    for ch in value:
        if ch.isdigit():
            space *= 10
        elif ch.isalpha():
            space *= 26
        if space > 10**9:
            return 10**9
    return space


def estimate_pool(col_type: str, values) -> int:
    """How many distinct fakes are available for these values."""
    if col_type in ("format_preserving", "number"):
        spaces = [_shape_space(v) for v in values if v]
        return min(spaces) if spaces else 10**9
    return _POOL_SIZES.get(col_type, 1_000)


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
    "number": "Number (same magnitude)",
    "format_preserving": "ID / code (keep format)",
    "custom_word": "Generic word",
}
