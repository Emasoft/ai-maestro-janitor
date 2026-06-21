"""Tests for session-liveness detection (TRDD-dccb0b8a, Phase 1).

Pure-function truth table — real values, no mocks. The load-bearing safety
property: an actively-working OR merely-idle session is NEVER classified frozen
(we must not inject recovery keystrokes into a healthy session), while the exact
2026-06-20→21 freeze shape (stale rate-limit flag + no transcript progress) IS.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import session_liveness as sl  # type: ignore[import-not-found]  # noqa: E402

_HB = 300  # heartbeat interval (s)
_FF = 3    # freeze factor → 15 min of no-progress before "frozen"


def test_no_flag_is_never_frozen() -> None:
    """A session with no rate-limit flag is idle/healthy — never poke it."""
    assert not sl.is_session_frozen(
        transcript_mtime=1000, rate_limited_since=None, flag_present=False,
        now=999999, heartbeat_interval_s=_HB, freeze_factor=_FF,
    )


def test_fresh_rate_limit_is_not_frozen_yet() -> None:
    """A rate-limit younger than freeze_factor heartbeats gets a chance to
    self-recover via the in-session cron before the daemon intervenes."""
    now = 1_000_000
    assert not sl.is_session_frozen(
        transcript_mtime=now - 60, rate_limited_since=now - 300,  # 5 min < 15 min
        flag_present=True, now=now, heartbeat_interval_s=_HB, freeze_factor=_FF,
    )


def test_stale_flag_no_progress_is_frozen() -> None:
    """The exact freeze shape: flag set 20h ago, transcript silent since → the
    in-session cron is dead, the session is stuck, the daemon must wake it."""
    now = 1_000_000
    rl = now - 20 * 3600          # rate-limited 20h ago
    assert sl.is_session_frozen(
        transcript_mtime=rl,       # no progress since the flag
        rate_limited_since=rl, flag_present=True, now=now,
        heartbeat_interval_s=_HB, freeze_factor=_FF,
    )


def test_progress_after_flag_means_recovered() -> None:
    """If the transcript advanced AFTER the flag, the session recovered or is
    working — NEVER poke it, even when the flag itself is stale."""
    now = 1_000_000
    rl = now - 20 * 3600
    assert not sl.is_session_frozen(
        transcript_mtime=rl + 600,  # 10 min of progress after the rate-limit
        rate_limited_since=rl, flag_present=True, now=now,
        heartbeat_interval_s=_HB, freeze_factor=_FF,
    )


def test_grace_window_absorbs_death_burst() -> None:
    """The few transcript writes in the rate-limit death-burst (the errors logged
    just after the flag) are within grace and do NOT count as recovery."""
    now = 1_000_000
    rl = now - 20 * 3600
    assert sl.is_session_frozen(
        transcript_mtime=rl + 5,   # death-burst write, within default grace 120s
        rate_limited_since=rl, flag_present=True, now=now,
        heartbeat_interval_s=_HB, freeze_factor=_FF,
    )


def test_cooldown_blocks_rapid_repoke() -> None:
    """One wake, then wait a full cooldown before the next attempt."""
    now = 1_000_000
    assert sl.recovery_cooldown_ok(None, now, 600)            # never poked → ok
    assert not sl.recovery_cooldown_ok(now - 60, now, 600)    # 1 min ago → wait
    assert sl.recovery_cooldown_ok(now - 700, now, 600)       # 11 min ago → ok


def test_escalation_tiers() -> None:
    """Two attempts per tier, capped at 3 — never loop past the relaunch tier."""
    assert sl.escalation_tier(0) == 1
    assert sl.escalation_tier(1) == 1
    assert sl.escalation_tier(2) == 2
    assert sl.escalation_tier(3) == 2
    assert sl.escalation_tier(4) == 3
    assert sl.escalation_tier(99) == 3


def test_capture_terminal_identity_extracts_present_keys() -> None:
    """Records the iTerm session id + term program this session reports; ignores
    unrelated env. This is exactly what was observed live: iTerm sets
    ITERM_SESSION_ID, TMUX_PANE was absent in subprocesses."""
    env = {"ITERM_SESSION_ID": "w0t9p0:ABC", "TERM_PROGRAM": "iTerm.app", "FOO": "bar"}
    assert sl.capture_terminal_identity(env) == {
        "iterm_session_id": "w0t9p0:ABC",
        "term_program": "iTerm.app",
    }


def test_capture_terminal_identity_omits_absent_and_blank() -> None:
    """Absent or whitespace-only ids are omitted so the daemon never targets a
    bogus pane; a real tmux pane id is kept."""
    assert sl.capture_terminal_identity({}) == {}
    assert sl.capture_terminal_identity({"TMUX_PANE": "   "}) == {}
    assert sl.capture_terminal_identity({"TMUX_PANE": "%3"}) == {"tmux_pane": "%3"}
