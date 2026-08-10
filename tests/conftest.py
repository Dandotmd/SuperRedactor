"""Seeded randomness for the randomized property tests.

`tests/test_property_no_leak.py` draws fresh data on every run — that is how
it keeps finding leaks nobody thought to look for, and it stays that way. The
price of fresh data is a failure you cannot reproduce, so every run picks one
run seed, prints it whether the suite passes or fails, and every generated
value descends from it. To run the same data again:

    SUPERREDACTOR_TEST_SEED=<seed> pytest tests/test_property_no_leak.py

Each test derives its own seed from the run seed and its node id, so replaying
a single failing test reproduces exactly the data it saw, with or without the
rest of the suite. The derivation is a SHA-256 digest rather than `hash()`
precisely so it does not move with `PYTHONHASHSEED`.
"""

from __future__ import annotations

import hashlib
import os
import random
from dataclasses import dataclass

import pytest
from faker import Faker

SEED_ENV = "SUPERREDACTOR_TEST_SEED"

_run_seed: int | None = None
_run_seed_forced = False
_recorded: list[Seeded] = []


def run_seed() -> tuple[int, bool]:
    """The seed for this whole process, and whether the env var forced it.

    Resolved once and reused, so every test in a run shares one number the
    reader has to write down.
    """
    global _run_seed, _run_seed_forced
    if _run_seed is None:
        raw = os.environ.get(SEED_ENV, "").strip()
        if raw:
            try:
                _run_seed = int(raw, 0)
            except ValueError:
                raise pytest.UsageError(
                    f"{SEED_ENV}={raw!r} is not an integer"
                ) from None
            _run_seed_forced = True
        else:
            # A new draw every run: the point of these tests is the data
            # nobody has tried yet.
            _run_seed = random.SystemRandom().randrange(2**32)
    return _run_seed, _run_seed_forced


def _derive(run: int, node_id: str) -> int:
    digest = hashlib.sha256(f"{run}:{node_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


@dataclass(frozen=True)
class Seeded:
    """One test's randomness, and the words to say to get it back."""

    seed: int
    run_seed: int
    forced: bool
    node_id: str
    rng: random.Random
    faker: Faker

    @property
    def replay(self) -> str:
        """Append to an assertion message so the failure can be re-run."""
        return (
            f"\n\n  run seed {self.run_seed}, this test drew from {self.seed}."
            f"\n  Replay exactly this data with:"
            f"\n      {SEED_ENV}={self.run_seed} pytest {self.node_id}"
        )


@pytest.fixture
def seeded(request: pytest.FixtureRequest) -> Seeded:
    """Randomness that is different every run and repeatable on demand.

    Both sources are seeded: `seeded.rng` for the test's own choices and
    `seeded.faker` for the values. Faker instances are per-test rather than
    module-level, so one test's draws cannot shift another's.
    """
    run, forced = run_seed()
    node_id = request.node.nodeid
    seed = _derive(run, node_id)
    faker = Faker()
    faker.seed_instance(seed)
    rig = Seeded(
        seed=seed,
        run_seed=run,
        forced=forced,
        node_id=node_id,
        rng=random.Random(seed),
        faker=faker,
    )
    _recorded.append(rig)
    return rig


def pytest_terminal_summary(terminalreporter) -> None:
    """Print the seeds on the way out, passing or failing.

    On a green run this is the record of what was actually covered; on a red
    one it is the second copy of the number, in case the assertion scrolled
    away.
    """
    if not _recorded:
        return
    run, forced = run_seed()
    source = f"forced by {SEED_ENV}" if forced else "drawn fresh this run"
    terminalreporter.write_sep("-", "randomized test seeds")
    terminalreporter.write_line(f"run seed {run} ({source})")
    for rig in _recorded:
        terminalreporter.write_line(f"  {rig.seed:>20}  {rig.node_id}")
    terminalreporter.write_line(f"replay: {SEED_ENV}={run} pytest tests/")
