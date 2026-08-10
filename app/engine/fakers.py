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
    """Produces fake values for one column. Values are unique within the
    generator and never equal to the real value they replace."""

    def __init__(self, col_type: str, seed: int | None = None):
        if col_type not in REDACTION_TYPES:
            raise ValueError(f"Unknown redaction type: {col_type}")
        self.col_type = col_type
        self._faker = Faker()
        self._rng = random.Random(seed)
        if seed is not None:
            self._faker.seed_instance(seed)
        self._issued: set[str] = set()

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
        for _ in range(100):
            fake = self._candidate(real)
            if fake != real and fake not in self._issued:
                self._issued.add(fake)
                return fake
        # Generator space exhausted (e.g. thousands of first names):
        # de-collide with a numeric suffix rather than fail.
        base = self._candidate(real)
        n = 2
        while f"{base} {n}" in self._issued or f"{base} {n}" == real:
            n += 1
        fake = f"{base} {n}"
        self._issued.add(fake)
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
    "number": "Number (same magnitude)",
    "format_preserving": "ID / code (keep format)",
    "custom_word": "Generic word",
}
