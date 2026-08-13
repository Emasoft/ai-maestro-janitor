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
    """The ladder escalates gentlest→hard-restart — rung 1 (ESC+nudge) is NOT the whole
    thing ('1 is not enough'): re-arm, reload, update, relaunch, force_restart,
    resurrect follow."""
    assert sl.recovery_action_for(0) == "esc_nudge"
    assert sl.recovery_action_for(1) == "rearm"
    assert sl.recovery_action_for(2) == "reload"
    assert sl.recovery_action_for(3) == "update"
    assert sl.recovery_action_for(4) == "relaunch"
    assert sl.recovery_action_for(5) == "force_restart"
    assert sl.recovery_action_for(6) == "resurrect"


def test_recovery_ladder_clamps_to_hard_restart() -> None:
    """Sustained failure stays at the hard-restart rung, never wraps to a gentle no-op
    that could never recover a hard freeze."""
    assert sl.recovery_action_for(7) == "resurrect"
    assert sl.recovery_action_for(99) == "resurrect"
    assert sl.recovery_action_for(-1) == "esc_nudge"


def test_hard_rung_classification() -> None:
    """Only the process-killing/replacing rungs are hard-restart (guard-bounded)."""
    assert not sl.is_hard_rung("esc_nudge")
    assert not sl.is_hard_rung("rearm")
    assert not sl.is_hard_rung("reload")
    assert not sl.is_hard_rung("update")
    assert sl.is_hard_rung("relaunch")
    assert sl.is_hard_rung("force_restart")
    assert sl.is_hard_rung("resurrect")


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


# --- TRDD-WKTD5JTC: retry-watchdog wedge detection --------------------------------

def test_is_retry_wedge_cause_agnostic_not_keyed_on_429() -> None:
    """Cause-agnostic (owner incident 2026-07-24): keys ONLY on the invariant shape
    'Retrying in ... attempt N/M', matching BOTH the 429 wedge AND the session-limit
    wedge (which carries no 429 at all). Rejects text that merely mentions '429' /
    'rate limit' without the retry+attempt signature — the cause-KEYED substring match
    this TRDD explicitly supersedes."""
    assert sl.is_retry_wedge("429 Rate limited · Retrying in 0s · attempt 5/300")
    assert sl.is_retry_wedge(
        "✻ Session limit reached · Retrying in 2m 50s (2:10pm) · attempt 1/300"
    )
    assert not sl.is_retry_wedge("we hit a 429 rate limit error earlier today")
    assert not sl.is_retry_wedge("rate limited, please wait")
    assert not sl.is_retry_wedge("")


def test_retry_wedge_attempt_extracts_the_number() -> None:
    """The attempt counter is the ONLY thing that can prove real progress — extract it."""
    assert sl.retry_wedge_attempt("429 Rate limited · Retrying in 0s · attempt 5/300") == 5
    assert sl.retry_wedge_attempt("Retrying in 2m 50s · attempt 12/300") == 12
    assert sl.retry_wedge_attempt("nothing here") is None


def test_retry_wedge_state_advance_decrease_tie_cleared() -> None:
    """The full episode state machine (advisor correction #3): first sighting is NOT
    yet wedged (no advance to compare against); a genuine ADVANCE confirms wedged; a
    DECREASE starts a fresh, again-unconfirmed episode; a TIE is not progress by
    itself but does not cancel an already-confirmed episode (long backoffs can exceed
    the beat); no signature clears the state entirely."""
    # first sighting — baseline only, not yet wedged
    st1, wedged1 = sl.retry_wedge_state_update(prev=None, current_attempt=5)
    assert st1 == {"attempt": 5, "confirmed": False}
    assert wedged1 is False
    # advance — confirmed wedged
    st2, wedged2 = sl.retry_wedge_state_update(prev=st1, current_attempt=6)
    assert st2 == {"attempt": 6, "confirmed": True}
    assert wedged2 is True
    # tie on a confirmed episode — stays wedged (backoff exceeded the beat)
    st3, wedged3 = sl.retry_wedge_state_update(prev=st2, current_attempt=6)
    assert st3 == {"attempt": 6, "confirmed": True}
    assert wedged3 is True
    # decrease — a NEW episode starts, unconfirmed again (never carries the old confirm)
    st4, wedged4 = sl.retry_wedge_state_update(prev=st3, current_attempt=1)
    assert st4 == {"attempt": 1, "confirmed": False}
    assert wedged4 is False
    # tie on an UNCONFIRMED episode — still not wedged (no advance ever seen)
    st5, wedged5 = sl.retry_wedge_state_update(prev=st4, current_attempt=1)
    assert st5 == {"attempt": 1, "confirmed": False}
    assert wedged5 is False
    # signature gone — state cleared entirely, regardless of prior confirmation
    st6, wedged6 = sl.retry_wedge_state_update(prev=st2, current_attempt=None)
    assert st6 is None
    assert wedged6 is False


def test_retry_wedge_never_self_triggers_on_a_static_display() -> None:
    """The exact self-trigger hazard this TRDD warns about: this file's own prose
    quotes the wedge line verbatim. A pane STATICALLY showing that fixed text (e.g.
    someone `cat`s this very TRDD) matches `is_retry_wedge` every poll — but the
    attempt number never changes, so `retry_wedge_state_update` never confirms it."""
    static_text = (
        "the wedge fires: `429 Rate limited · Retrying in 0s · attempt 5/300`"
    )
    assert sl.is_retry_wedge(static_text)  # the regex DOES match static prose
    state_ = None
    wedged = False
    for _ in range(5):  # repeated polls of the SAME static text
        attempt = sl.retry_wedge_attempt(static_text)
        state_, wedged = sl.retry_wedge_state_update(prev=state_, current_attempt=attempt)
        assert wedged is False, "a static display must never confirm as wedged"


def test_diagnose_instance_retry_wedged_ranks_above_frozen() -> None:
    """retry_wedged is checked BEFORE frozen (design §2): a pane that shows BOTH the
    wedge signature AND a stale rate-limited flag must route through retry_wedged's
    OWN esc-only entry, never frozen's 'ladder' (which can escalate to a kill)."""
    assert sl.diagnose_instance(
        deliberately_unarmed=False, pane_alive=True, transcript_stale=True,
        rate_limited=True, version_stale=False, retry_wedged=True,
    ) == "retry_wedged"
    # without retry_wedged, the same inputs fall through to frozen as before
    assert sl.diagnose_instance(
        deliberately_unarmed=False, pane_alive=True, transcript_stale=True,
        rate_limited=True, version_stale=False, retry_wedged=False,
    ) == "frozen"
    # unarmed/server_owned/dead/healthy still outrank it
    assert sl.diagnose_instance(
        deliberately_unarmed=True, pane_alive=True, transcript_stale=True,
        rate_limited=True, version_stale=False, retry_wedged=True,
    ) == "unarmed"
    assert sl.diagnose_instance(
        deliberately_unarmed=False, pane_alive=True, transcript_stale=False,
        rate_limited=True, version_stale=False, retry_wedged=True,
    ) == "healthy"


def test_retry_wedged_recovery_is_not_ladder() -> None:
    """Advisor correction #1: retry_wedged gets its OWN entry, never 'ladder' — 'ladder'
    is frozen's 7-rung escalation and eventually reaches force_restart (a kill), which a
    retry-wedge (never a crashed process) must never reach."""
    assert sl.recovery_for_diagnosis("retry_wedged") is not None  # actionable
    assert sl.recovery_for_diagnosis("retry_wedged") != "ladder"
    assert sl.recovery_for_diagnosis("retry_wedged") == "esc_retry"


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
