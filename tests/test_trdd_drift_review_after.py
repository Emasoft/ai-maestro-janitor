"""`review-after:` — the expiring snooze for a DELIBERATELY parked TRDD.

WHY THIS EXISTS. `trdd-drift` treats `backburner` as drift-eligible on purpose: most
parked TRDDs are simply forgotten work, and surfacing them is the point. But some are
parked for a stated reason — TRDD-de731408 is shelved pending an upstream Claude Code
change, and had been nagged for 49 days at the time this shipped. A detector that cries
wolf on a correctly-parked file trains its reader to ignore it, which costs more than the
false positive itself.

The two obvious "fixes" are both worse. Bumping `updated:` to quiet the detector asserts
the file changed when nothing did. A bare `shelved` label silences it FOREVER — the exact
failure the janitor already learned the hard way, when a temporary global disarm went
unnoticed for ~33h because nothing carried its duration or reason.

So the snooze is a DATE, and it expires by itself. These tests pin that: honoured before,
gone after, and — the load-bearing half — a malformed or nonsense date must NEVER silence
a TRDD, because a snooze that fails open is a snooze that hides work.
"""

from __future__ import annotations

import importlib.util
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_DETECTOR = Path(__file__).resolve().parent.parent / "scripts" / "detectors" / "trdd-drift.py"


@pytest.fixture()
def drift():
    spec = importlib.util.spec_from_file_location("trdd_drift_under_test", _DETECTOR)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _head(date: str | None) -> str:
    body = [
        "---",
        "trdd-id: DE731408",
        "title: a deliberately parked task",
        "column: backburner",
    ]
    if date is not None:
        body.append(f"review-after: {date}")
    body += ["---", "", "# body"]
    return "\n".join(body)


def test_a_trdd_without_the_field_declares_no_snooze(drift):
    """The default must stay "check it" — the field is opt-in, never inferred."""
    assert drift.review_after_epoch(_head(None)) is None


def test_a_well_formed_date_parses_to_that_local_midnight(drift):
    """The park is honoured until the stated day begins, in the reader's own timezone."""
    got = drift.review_after_epoch(_head("2026-09-01"))

    assert got == int(datetime(2026, 9, 1).astimezone().timestamp())


def test_a_future_date_is_still_in_the_future(drift):
    """The property the detector actually branches on: now < review_after ⇒ stay silent."""
    future = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

    assert drift.review_after_epoch(_head(future)) > int(time.time())


def test_a_past_date_has_expired_so_the_trdd_is_checked_again(drift):
    """A park a human forgot re-surfaces on its own — that is the whole point of a date."""
    past = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    assert drift.review_after_epoch(_head(past)) < int(time.time())


@pytest.mark.parametrize(
    "bad",
    [
        "2026-02-31",   # a real-looking date that does not exist
        "2026-13-01",   # month out of range
        "not-a-date",
        "2026/09/01",   # wrong separator
        "26-09-01",     # two-digit year
        "",             # present but empty
    ],
)
def test_a_malformed_snooze_never_silences_the_trdd(drift, bad):
    """FAIL-OPEN is the load-bearing property: a typo must not hide work indefinitely.

    Returning None puts the TRDD back on the normal drift path, so the worst case of a
    mistyped snooze is a nag — never silence.
    """
    assert drift.review_after_epoch(_head(bad)) is None


def test_the_field_must_sit_at_column_zero_not_inside_prose(drift):
    """Frontmatter is line-anchored; a TRDD that merely DISCUSSES review-after is not parked.

    Without the anchor, a page explaining this very feature would snooze itself — the same
    class of bug as a lessons-heading matched as a substring.
    """
    prose = _head(None) + "\n\nSee the `review-after: 2099-01-01` field documented above.\n"

    assert drift.review_after_epoch(prose) is None


def test_the_first_declaration_wins_when_a_page_repeats_it(drift):
    """Deterministic on a malformed page: pick one, never flap between sweeps."""
    doubled = _head("2026-09-01") + "\nreview-after: 2030-01-01\n"

    assert drift.review_after_epoch(doubled) == int(datetime(2026, 9, 1).astimezone().timestamp())
