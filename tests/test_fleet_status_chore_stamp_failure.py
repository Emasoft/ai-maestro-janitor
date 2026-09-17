"""GH#297 / TRDD-3GF9PSQB: a chore's last-run stamp is written unconditionally, on
failure as well as success (daemon.py::Task.run / poll_background), so a task
failing every run still reports as freshly refreshed. `_fmt_chore_stamp` is the
fix for the fleet-status dashboard line named in the issue as one of the readers
that never consulted the failure streak beside the timestamp.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import fleet_status as fstat  # type: ignore[import-not-found]  # noqa: E402


def test_healthy_chore_shows_bare_timestamp():
    ts = 1_700_000_000
    out = fstat._fmt_chore_stamp(ts, fails=0, quarantine_after=3)
    assert out == fstat._fmt_ts(ts)
    assert "FAILING" not in out


def test_chore_failing_past_quarantine_threshold_is_flagged():
    ts = 1_700_000_000
    out = fstat._fmt_chore_stamp(ts, fails=11, quarantine_after=3)
    assert "QUARANTINED 11x" in out
    # the timestamp itself must still be present — a failing chore is not a
    # reason to also hide WHEN the last (failed) attempt happened
    assert fstat._fmt_ts(ts) in out


def test_chore_single_failure_below_quarantine_is_still_flagged():
    # Coordinator-review follow-up (GH#297): gating "healthy" on the daemon's
    # quarantine threshold (3) left kill #1 and kill #2 showing a bare fresh
    # age — the issue's exact complaint. A test that only passes at the
    # threshold would not have caught that; assert fails=1 flags too.
    ts = 1_700_000_000
    out = fstat._fmt_chore_stamp(ts, fails=1, quarantine_after=3)
    assert "FAILING 1x" in out
    assert "QUARANTINED" not in out
    assert fstat._fmt_ts(ts) in out


