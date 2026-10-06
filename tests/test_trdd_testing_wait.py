"""closeable-candidate vs a `testing` card correctly waiting on a live event (janitor#332, TRDD-8BNV75TV).

Pure over a parsed record and a fake tag map — no real git.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import trdd_common as tc  # noqa: E402

_STATE_HDR = "## ⏵ STATE — READ THIS FIRST ON RESUME — 2026-10-07"
_TODAY = date(2026, 10, 7)
_LIVE = "waiting for a live rotation event that cannot be forced."


def _testing_reconcile(state: str, *, updated: str = "2026-10-01", log: str = ""):
    text = (
        "---\ntrdd-id: TESTID01\ntitle: T\ncolumn: testing\nblocked-by: []\n"
        f"implementation-commits: [abc1234]\nupdated: {updated}T00:00:00+0200\n---\n"
        f"\n{_STATE_HDR}\n{state}\n\n## Approval log\n\n{log}"
    )
    rec = tc.parse_record_text(text, uid="TESTID01")
    return tc.reconcile(rec, lambda sha: sha == "abc1234", lambda uid: "", today=_TODAY)


def test_testing_card_waiting_on_live_event_with_recent_field_check_is_not_closeable():
    v = _testing_reconcile(f"{_LIVE}\nfield check 2026-10-05: 0 lines yet.")
    assert "closeable-candidate" not in v.fired


def test_testing_card_with_an_old_field_check_is_still_closeable():
    v = _testing_reconcile(f"{_LIVE}\nfield check 2026-08-01: 0 lines yet.")
    assert "closeable-candidate" in v.fired


def test_testing_card_without_a_field_check_is_still_closeable():
    assert "closeable-candidate" in _testing_reconcile(_LIVE).fired


def test_testing_card_over_the_ceiling_is_flagged_despite_a_recent_field_check():
    v = _testing_reconcile(
        f"{_LIVE}\nfield check 2026-10-05: 0 lines yet.",
        log="- 2026-08-08T10:00:00+0200 — column -> testing by main-agent@x\n",
    )
    assert "testing-too-long" in v.fired


def test_testing_age_falls_back_to_updated_when_the_log_has_no_move():
    assert "testing-too-long" in _testing_reconcile(_LIVE, updated="2026-07-01").fired
    assert "testing-too-long" not in _testing_reconcile(_LIVE, updated="2026-10-01").fired
