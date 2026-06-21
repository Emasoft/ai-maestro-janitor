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


def test_recovery_ladder_full_sequence() -> None:
    """The ladder escalates gentlest→nuclear — rung 1 (ESC+nudge) is NOT the whole
    thing ('1 is not enough'): re-arm, reload, update, relaunch, force_restart,
    resurrect follow."""
    assert sl.recovery_action_for(0) == "esc_nudge"
    assert sl.recovery_action_for(1) == "rearm"
    assert sl.recovery_action_for(2) == "reload"
    assert sl.recovery_action_for(3) == "update"
    assert sl.recovery_action_for(4) == "relaunch"
    assert sl.recovery_action_for(5) == "force_restart"
    assert sl.recovery_action_for(6) == "resurrect"


def test_recovery_ladder_clamps_to_nuclear() -> None:
    """Sustained failure stays at the nuclear rung, never wraps to a gentle no-op
    that could never recover a hard freeze."""
    assert sl.recovery_action_for(7) == "resurrect"
    assert sl.recovery_action_for(99) == "resurrect"
    assert sl.recovery_action_for(-1) == "esc_nudge"


def test_nuclear_rung_classification() -> None:
    """Only the process-killing/replacing rungs are nuclear (guard-bounded)."""
    assert not sl.is_nuclear_rung("esc_nudge")
    assert not sl.is_nuclear_rung("rearm")
    assert not sl.is_nuclear_rung("reload")
    assert not sl.is_nuclear_rung("update")
    assert sl.is_nuclear_rung("relaunch")
    assert sl.is_nuclear_rung("force_restart")
    assert sl.is_nuclear_rung("resurrect")


def test_crash_loop_guard() -> None:
    """A restart storm trips the guard → the one place auto-recovery pages a
    human, precisely because recovery itself is looping."""
    assert not sl.crash_loop_tripped(0, 3)
    assert not sl.crash_loop_tripped(2, 3)
    assert sl.crash_loop_tripped(3, 3)
    assert sl.crash_loop_tripped(5, 3)


def test_diagnose_instance_unarmed_is_sacrosanct() -> None:
    """A deliberately-unarmed instance is NEVER touched, even when every other
    signal screams broken — the user opted out and that overrides everything."""
    assert sl.diagnose_instance(
        deliberately_unarmed=True, pane_alive=True, transcript_stale=True,
        rate_limited=True, version_stale=True,
    ) == "unarmed"
    assert sl.recovery_for_diagnosis("unarmed") is None


def test_diagnose_instance_fresh_transcript_is_never_touched() -> None:
    """A session whose transcript is advancing is healthy even with a rate-limit
    flag and a stale version — it is working OR its heartbeat is firing (both
    append to the transcript), and nudging it would corrupt live work. THE
    load-bearing false-positive guard, and why dispatch.log (silent on quiet
    fires) is the WRONG signal."""
    assert sl.diagnose_instance(
        deliberately_unarmed=False, pane_alive=True, transcript_stale=False,
        rate_limited=True, version_stale=True,
    ) == "healthy"


def test_diagnose_instance_precedence() -> None:
    """Most-severe/actionable wins: unarmed > dead > healthy(fresh transcript) >
    frozen > version_mismatch > cron_dead. This is the fleet-guardian's whole
    decision table."""
    base = {"deliberately_unarmed": False}
    assert sl.diagnose_instance(**base, pane_alive=False, transcript_stale=True, rate_limited=True, version_stale=True) == "dead"
    assert sl.diagnose_instance(**base, pane_alive=True, transcript_stale=False, rate_limited=True, version_stale=True) == "healthy"
    assert sl.diagnose_instance(**base, pane_alive=True, transcript_stale=True, rate_limited=True, version_stale=True) == "frozen"
    assert sl.diagnose_instance(**base, pane_alive=True, transcript_stale=True, rate_limited=False, version_stale=True) == "version_mismatch"
    assert sl.diagnose_instance(**base, pane_alive=True, transcript_stale=True, rate_limited=False, version_stale=False) == "cron_dead"


def test_diagnose_recovery_mapping() -> None:
    """Each diagnosis maps to the right OUTSIDE recovery; healthy/unknown = leave
    alone (fail-safe: never invent an action for a state we don't recognize)."""
    assert sl.recovery_for_diagnosis("frozen") == "ladder"
    assert sl.recovery_for_diagnosis("version_mismatch") == "reload"
    assert sl.recovery_for_diagnosis("cron_dead") == "rearm"
    assert sl.recovery_for_diagnosis("dead") == "relaunch"
    assert sl.recovery_for_diagnosis("healthy") is None
    assert sl.recovery_for_diagnosis("unknown_state") is None


def test_normalize_tty_variants() -> None:
    """ps ('s003'), lsof/iTerm ('/dev/ttys003'), and a bare 'ttys003' must all
    compare EQUAL — that cross-source match is what lets the daemon map a claude
    process's TTY to its terminal for a fleet rescue."""
    assert sl.normalize_tty("/dev/ttys003") == "ttys003"
    assert sl.normalize_tty("ttys003") == "ttys003"
    assert sl.normalize_tty("s003") == "ttys003"
    assert sl.normalize_tty("  /dev/ttys012  ") == "ttys012"
    assert sl.normalize_tty("?") == ""
    assert sl.normalize_tty("") == ""


def test_resolve_terminal_for_tty() -> None:
    """A process's TTY resolves to its terminal id WITHOUT the session having
    recorded anything — the only path to an old/zombie instance running a janitor
    too old to have written terminal-identity.json."""
    iterm = {"ttys003": "w0t1p0:UUID"}
    tmux = {"ttys004": "%5"}
    assert sl.resolve_terminal_for_tty("ttys003", iterm_by_tty=iterm, tmux_by_tty=tmux) == {"iterm_session_id": "w0t1p0:UUID"}
    assert sl.resolve_terminal_for_tty("ttys004", iterm_by_tty=iterm, tmux_by_tty=tmux) == {"tmux_pane": "%5"}
    both = sl.resolve_terminal_for_tty("ttysX", iterm_by_tty={"ttysX": "u"}, tmux_by_tty={"ttysX": "%9"})
    assert both == {"tmux_pane": "%9", "iterm_session_id": "u"}
    assert sl.resolve_terminal_for_tty("", iterm_by_tty=iterm, tmux_by_tty=tmux) == {}
    assert sl.resolve_terminal_for_tty("ttysZ", iterm_by_tty=iterm, tmux_by_tty=tmux) == {}
