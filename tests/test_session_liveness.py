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


def test_hard_rung_classification() -> None:
    """Only `relaunch` is hard-restart (guard-bounded). The two kill rungs
    (force_restart, resurrect) were RETIRED — TRDD-56d24c02, executed by
    TRDD-V07NFXS9 — so they no longer classify as anything at all."""
    assert not sl.is_hard_rung("esc_nudge")
    assert not sl.is_hard_rung("rearm")
    assert not sl.is_hard_rung("reload")
    assert not sl.is_hard_rung("update")
    assert sl.is_hard_rung("relaunch")
    assert not sl.is_hard_rung("force_restart")
    assert not sl.is_hard_rung("resurrect")


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
    assert st1 == {"attempt": 5, "confirmed": False, "retry_in": None, "first_seen": None}
    assert wedged1 is False
    # advance — confirmed wedged
    st2, wedged2 = sl.retry_wedge_state_update(prev=st1, current_attempt=6)
    assert st2 == {
        "attempt": 6, "confirmed": True, "retry_in": None, "first_seen": None,
        "proof": "attempt-advance",
    }
    assert wedged2 is True
    # tie on a confirmed episode — stays wedged (backoff exceeded the beat)
    st3, wedged3 = sl.retry_wedge_state_update(prev=st2, current_attempt=6)
    assert st3 == {
        "attempt": 6, "confirmed": True, "retry_in": None, "first_seen": None,
        "proof": "attempt-advance",
    }
    assert wedged3 is True
    # decrease — a NEW episode starts, unconfirmed again (never carries the old confirm)
    st4, wedged4 = sl.retry_wedge_state_update(prev=st3, current_attempt=1)
    assert st4 == {"attempt": 1, "confirmed": False, "retry_in": None, "first_seen": None}
    assert wedged4 is False
    # tie on an UNCONFIRMED episode — still not wedged (no advance ever seen)
    st5, wedged5 = sl.retry_wedge_state_update(prev=st4, current_attempt=1)
    assert st5 == {"attempt": 1, "confirmed": False, "retry_in": None, "first_seen": None}
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



def _wedge_frame(retry_in: str, attempt: int = 1) -> str:
    """A real-shaped [CC] pane capture: the status row sits directly above the input box's
    upper border, and the status row starts with a status glyph at column 0."""
    border = "─" * 40
    return (
        "⏺ some earlier output\n"
        f"✻ Rate limited · Retrying in {retry_in} · attempt {attempt}/300\n"
        f"{border}\n"
        "❯ \n"
        f"{border}\n"
    )


def test_frozen_countdown_confirms_wedge() -> None:
    """Two polls >=100s apart with BYTE-IDENTICAL second-scale retry_in text and no attempt
    advance prove the countdown is frozen, not waiting (TRDD-RJJGXPIK)."""
    st1, wedged1 = sl.retry_wedge_state_update(
        prev=None, current_attempt=1, current_retry_in="30s", now=1000
    )
    assert wedged1 is False
    assert st1 == {"attempt": 1, "confirmed": False, "retry_in": "30s", "first_seen": 1000}
    st2, wedged2 = sl.retry_wedge_state_update(
        prev=st1, current_attempt=1, current_retry_in="30s", now=1120
    )
    assert wedged2 is True
    assert st2 == {
        "attempt": 1, "confirmed": True, "retry_in": "30s", "first_seen": 1000,
        "proof": "frozen-countdown",
    }


def test_frozen_countdown_below_threshold_no_confirm() -> None:
    """60s apart is below the 120s threshold — the countdown could still be a legitimately
    slow refresh, so no confirmation and the first_seen clock keeps running."""
    st1, _ = sl.retry_wedge_state_update(
        prev=None, current_attempt=1, current_retry_in="30s", now=1000
    )
    st2, wedged2 = sl.retry_wedge_state_update(
        prev=st1, current_attempt=1, current_retry_in="30s", now=1060
    )
    assert wedged2 is False
    assert st2 is not None
    assert st2["confirmed"] is False
    assert st2["first_seen"] == 1000  # still counting from the first sighting


def test_frozen_countdown_hour_scale_excluded() -> None:
    """`Retrying in 5h` legitimately holds identical text for hours — no second-level
    granularity means this path can never confirm a wedge."""
    st1, _ = sl.retry_wedge_state_update(
        prev=None, current_attempt=1, current_retry_in="5h", now=1000
    )
    st2, wedged2 = sl.retry_wedge_state_update(
        prev=st1, current_attempt=1, current_retry_in="5h", now=1120
    )
    assert wedged2 is False
    assert st2 is not None
    assert st2["confirmed"] is False
    assert st2["first_seen"] is None


def test_frozen_countdown_different_retry_in_resets() -> None:
    """A CHANGED countdown text is real progress (the timer ticked), so first_seen resets and
    nothing is confirmed."""
    st1, _ = sl.retry_wedge_state_update(
        prev=None, current_attempt=1, current_retry_in="30s", now=1000
    )
    st2, wedged2 = sl.retry_wedge_state_update(
        prev=st1, current_attempt=1, current_retry_in="25s", now=1120
    )
    assert wedged2 is False
    assert st2 is not None
    assert st2["confirmed"] is False
    assert st2["retry_in"] == "25s"
    assert st2["first_seen"] == 1120



def test_frozen_countdown_boundary_99_not_100_confirmed() -> None:
    """The confirmation bar is exactly 100 s (TRDD-RJJGXPIK): 99 s of identical text is not
    enough, 100 s is. The owner's words are "more than one or 2 minutes", and only a
    second-scale countdown reaches this bar, so 100 s byte-identical is unambiguously frozen."""
    st1, _ = sl.retry_wedge_state_update(
        prev=None, current_attempt=1, current_retry_in="30s", now=1000
    )
    _, wedged99 = sl.retry_wedge_state_update(
        prev=st1, current_attempt=1, current_retry_in="30s", now=1099
    )
    _, wedged100 = sl.retry_wedge_state_update(
        prev=st1, current_attempt=1, current_retry_in="30s", now=1100
    )
    assert wedged99 is False
    assert wedged100 is True


def test_frozen_countdown_confirms_on_a_119s_beat_gap() -> None:
    """The liveness beat is nominally 120 s and whole-second clocks make the real gap 119 s;
    that gap must confirm on the SECOND read (a 120 s bar needed a third, one beat later)."""
    st1, _ = sl.retry_wedge_state_update(
        prev=None, current_attempt=1, current_retry_in="30s", now=1000
    )
    st2, wedged2 = sl.retry_wedge_state_update(
        prev=st1, current_attempt=1, current_retry_in="30s", now=1119
    )
    assert wedged2 is True
    assert st2 is not None and st2["proof"] == sl.PROOF_FROZEN_COUNTDOWN


def test_proof_says_which_evidence_confirmed_the_wedge() -> None:
    """TRDD-RJJGXPIK: a confirmed state names its proof. An attempt advance (and a confirmation
    merely carried over a tie) is `attempt-advance`; only a countdown frozen THIS poll is
    `frozen-countdown`; an unconfirmed state carries no proof at all."""
    st1, _ = sl.retry_wedge_state_update(prev=None, current_attempt=1, current_retry_in="30s", now=1000)
    assert st1 is not None and "proof" not in st1
    adv, _ = sl.retry_wedge_state_update(prev=st1, current_attempt=2, current_retry_in="25s", now=1010)
    assert adv is not None and adv["proof"] == sl.PROOF_ATTEMPT_ADVANCE
    # a carried confirmation over a tie whose countdown TICKED: still attempt-advance
    tie, wedged = sl.retry_wedge_state_update(prev=adv, current_attempt=2, current_retry_in="20s", now=1020)
    assert wedged is True and tie is not None and tie["proof"] == sl.PROOF_ATTEMPT_ADVANCE
    # the same confirmed episode, countdown now byte-identical for >=100 s: frozen-countdown
    tie2, _ = sl.retry_wedge_state_update(prev=tie, current_attempt=2, current_retry_in="20s", now=1030)
    assert tie2 is not None and tie2["proof"] == sl.PROOF_ATTEMPT_ADVANCE  # clock just restarted
    tie3, _ = sl.retry_wedge_state_update(prev=tie2, current_attempt=2, current_retry_in="20s", now=1130)
    assert tie3 is not None and tie3["proof"] == sl.PROOF_FROZEN_COUNTDOWN
    # the countdown ticks again: the frozen proof is not carried
    tie4, _ = sl.retry_wedge_state_update(prev=tie3, current_attempt=2, current_retry_in="15s", now=1140)
    assert tie4 is not None and tie4["proof"] == sl.PROOF_ATTEMPT_ADVANCE


def test_fast_wedge_acts_only_on_a_confirmed_wedge_and_never_forces_staleness() -> None:
    """TRDD-RJJGXPIK: `fast_wedge` lets a confirmed frozen-countdown wedge win while the
    transcript is NOT stale — but it is consulted only on the retry_wedged branch. Alone it
    does nothing, and it never reroutes a non-stale instance into frozen / version_mismatch /
    cron_dead (which a forced `transcript_stale=True` would)."""
    base = dict(deliberately_unarmed=False, pane_alive=True, rate_limited=True, version_stale=True)
    assert sl.diagnose_instance(**base, transcript_stale=False, retry_wedged=True, fast_wedge=True) == "retry_wedged"
    assert sl.diagnose_instance(**base, transcript_stale=False, retry_wedged=True, fast_wedge=False) == "healthy"
    assert sl.diagnose_instance(**base, transcript_stale=False, retry_wedged=False, fast_wedge=True) == "healthy"
    # stale transcript: the old routing is untouched by the new flag
    assert sl.diagnose_instance(**base, transcript_stale=True, retry_wedged=True, fast_wedge=False) == "retry_wedged"
    assert sl.diagnose_instance(**base, transcript_stale=True, retry_wedged=False, fast_wedge=True) == "frozen"
    # the opt-outs still outrank it
    assert sl.diagnose_instance(
        **{**base, "deliberately_unarmed": True}, transcript_stale=False, retry_wedged=True, fast_wedge=True
    ) == "unarmed"
    assert sl.diagnose_instance(
        **base, transcript_stale=False, retry_wedged=True, fast_wedge=True, server_owned=True
    ) == "server_owned"


def test_frozen_countdown_zero_seconds_never_confirms() -> None:
    """A hung request shows `Retrying in 0s` forever; that is a different failure and must
    not be read as a frozen countdown (TRDD-RJJGXPIK). `0s` and `00s` never confirm, however
    long they persist, while `10s` (which merely ENDS in 0s) still does."""
    for zero in ("0s", "00s"):
        st1, _ = sl.retry_wedge_state_update(
            prev=None, current_attempt=1, current_retry_in=zero, now=1000
        )
        st2, wedged2 = sl.retry_wedge_state_update(
            prev=st1, current_attempt=1, current_retry_in=zero, now=5000
        )
        assert wedged2 is False, zero
        assert st2 is not None
        assert st2["confirmed"] is False, zero
    st1, _ = sl.retry_wedge_state_update(
        prev=None, current_attempt=1, current_retry_in="10s", now=1000
    )
    _, wedged = sl.retry_wedge_state_update(
        prev=st1, current_attempt=1, current_retry_in="10s", now=1120
    )
    assert wedged is True


def test_resume_marker_carried_within_episode_and_dropped_outside() -> None:
    """The daemon-written resume_sent marker survives polls of the SAME episode (tie and
    advance) so later beats stay ESC-only, and is dropped when the episode ends (no wedge on
    screen), restarts (attempt decreases) or the marker is older than RESUME_EPISODE_TTL_S
    (TRDD-RJJGXPIK)."""
    marked = {
        "attempt": 3, "confirmed": True, "retry_in": "30s", "first_seen": 1000,
        "resume_sent": True, "resume_sent_at": 2000,
    }
    assert sl.resume_sent_active(marked, 2000 + sl.RESUME_EPISODE_TTL_S) is True
    assert sl.resume_sent_active(marked, 2000 + sl.RESUME_EPISODE_TTL_S + 1) is False
    assert sl.resume_sent_active({"attempt": 3}, 2000) is False
    tie, _ = sl.retry_wedge_state_update(prev=marked, current_attempt=3, current_retry_in="30s", now=2100)
    assert tie is not None and tie["resume_sent"] is True and tie["resume_sent_at"] == 2000
    adv, _ = sl.retry_wedge_state_update(prev=marked, current_attempt=4, current_retry_in="30s", now=2100)
    assert adv is not None and adv["resume_sent"] is True
    # Marker-only state (daemon wrote it before any scan saw the wedge): kept at baseline.
    first, _ = sl.retry_wedge_state_update(
        prev={"resume_sent": True, "resume_sent_at": 2000}, current_attempt=3, now=2100
    )
    assert first is not None and first["resume_sent"] is True
    # Dropped: episode ended, new episode (attempt decrease), expired TTL.
    assert sl.retry_wedge_state_update(prev=marked, current_attempt=None, now=2100) == (None, False)
    new_ep, _ = sl.retry_wedge_state_update(prev=marked, current_attempt=1, current_retry_in="30s", now=2100)
    assert new_ep is not None and "resume_sent" not in new_ep
    stale, _ = sl.retry_wedge_state_update(
        prev=marked, current_attempt=3, current_retry_in="30s", now=2000 + sl.RESUME_EPISODE_TTL_S + 1
    )
    assert stale is not None and "resume_sent" not in stale


def test_advance_still_confirms() -> None:
    """The original advance-across-polls guard is unchanged and takes priority."""
    st1, _ = sl.retry_wedge_state_update(prev=None, current_attempt=1, now=1000)
    st2, wedged2 = sl.retry_wedge_state_update(
        prev=st1, current_attempt=2, current_retry_in="30s", now=1001
    )
    assert wedged2 is True
    assert st2 is not None
    assert st2["attempt"] == 2
    assert st2["confirmed"] is True


def test_retry_wedge_retry_in_extracts() -> None:
    """The countdown text is pulled from the status row, not from anywhere else in the frame."""
    assert sl.retry_wedge_retry_in(_wedge_frame("30s", attempt=1)) == "30s"
    assert sl.retry_wedge_retry_in(_wedge_frame("0s", attempt=5)) == "0s"


def test_retry_wedge_retry_in_returns_none_when_no_wedge() -> None:
    """A pane with no retry-wedge status row yields None (never a stray match from prose)."""
    assert sl.retry_wedge_retry_in("⏺ Retrying in 30s · attempt 1/300\n" + "─" * 40 + "\n❯ \n") is None
    assert sl.retry_wedge_retry_in("") is None


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
    is frozen's escalation label, which historically could reach a kill rung (now
    retired) — a retry-wedge (never a crashed process) must never reach one."""
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


def test_iterm_channel_evidence_counts_a_busy_read_not_only_a_fired_rearm() -> None:
    """A pane READ that found the input field busy PROVES the Apple Event answered — so it is
    positive channel evidence, exactly like a fired rearm (janitor#261).

    Counting only `FIRED rearm` measured "did the guardian have work recently", not "does the
    channel work". On a healthy fleet the guardian usually has nothing to rearm, so the
    evidence age grew without bound while nothing was wrong, and the alarm read as an
    escalating failure. Measured on the owner's host: 15 BUSY lines vs 9 FIRED — the
    uncounted outcome was the MORE COMMON one, which is why the misread lasted seven fires.
    """
    import session_liveness as sl  # type: ignore[import-not-found]

    fired = "[2026-08-13T06:21:49+0200] session-liveness: FIRED rearm → iterm for X [cron_dead]"
    busy = (
        "[2026-08-13T06:51:04+0200] session-liveness: X [cron_dead] attempt=0 "
        "INPUT FIELD BUSY on iterm — would rearm; skipped"
    )
    # The BUSY line is NEWER, so a parser that ignores it reports a staler channel than reality.
    both = sl.latest_iterm_rearm_epoch(f"{fired}\n{busy}\n")
    only_fired = sl.latest_iterm_rearm_epoch(f"{fired}\n")
    assert both is not None and only_fired is not None
    assert both > only_fired, "a busy-read must count as channel evidence, not be discarded"

    # Each shape alone is sufficient evidence.
    assert sl.latest_iterm_rearm_epoch(busy) is not None
    assert sl.latest_iterm_rearm_epoch(fired) is not None

    # A line proving NOTHING about the channel is still ignored — widening the evidence set
    # must not become "any log line counts", or the alarm can never fire at all.
    assert sl.latest_iterm_rearm_epoch(
        "[2026-08-13T07:00:00+0200] session-liveness: X [cron_dead] no channel resolved"
    ) is None
