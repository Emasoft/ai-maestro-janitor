"""Tests for the fleet recovery POLICY (TRDD-324223a6, GROUP A / A2).

Pure decisions — which action to inject for a diagnosis at a given attempt count,
and whether an attempt is allowed now. The load-bearing properties: a healthy or
deliberately-unarmed session yields NO action (never poked); a frozen session walks
the ladder gentlest→strongest; the crash-loop guard wins over an elapsed cooldown
(a spent budget must always stop the poking).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import fleet_recovery as fr  # type: ignore[import-not-found]  # noqa: E402
import session_liveness as sl  # type: ignore[import-not-found]  # noqa: E402


def test_action_for_per_diagnosis() -> None:
    """cron_dead re-arms, version_mismatch reloads, and the never-touch diagnoses
    (healthy/unarmed) plus the hard-restart-only one (dead) yield no typed action."""
    assert fr.action_for("cron_dead", 0) == "rearm"
    assert fr.action_for("version_mismatch", 0) == "reload"
    assert fr.action_for("healthy", 0) is None
    assert fr.action_for("unarmed", 0) is None
    assert fr.action_for("dead", 0) is None       # → hard-restart A5, not a typed command
    assert fr.action_for("nonsense", 0) is None


def test_frozen_gentle_recovery_is_esc_only() -> None:
    """THE FLOOD FIX (TRDD-P7WU40G9): the GENTLE recovery for a frozen (rate-limited) session is
    ESC-ONLY (`esc_nudge`) at every attempt — never a typed slash-command that would accumulate on
    the retry-blocked input line and flood. The old command-typing ladder (rearm/reload/update) is
    gone. Without `include_hard` this is the WHOLE ladder (ESC forever, then the crash-loop guard)."""
    for attempt in (-1, 0, 1, 2, 3, 99):
        assert fr.action_for("frozen", attempt, resume_sent=True) == "esc_nudge", attempt


def test_frozen_and_retry_wedged_resume_exactly_once_per_episode() -> None:
    """TRDD-RJJGXPIK owner directive ("after pressing esc it should also inject the command
    resume"): the FIRST pass of a frozen / retry_wedged episode is `esc_nudge_resume`
    (ESC, settle, type `resume`); once the episode state records resume_sent the routing
    drops to ESC-only `esc_nudge`, so repeated beats never stack resumes. Neither phase is a
    hard (kill) rung, at any attempt count."""
    for diagnosis in ("frozen", "retry_wedged"):
        for attempt in (0, 1, 4, 99):
            assert fr.action_for(diagnosis, attempt) == "esc_nudge_resume", (diagnosis, attempt)
            assert fr.action_for(diagnosis, attempt, resume_sent=False) == "esc_nudge_resume"
            assert fr.action_for(diagnosis, attempt, resume_sent=True) == "esc_nudge"
            assert not sl.is_hard_rung("esc_nudge_resume")
    # The flag touches only the ESC wedge phases, never another diagnosis.
    assert fr.action_for("cron_dead", 0, resume_sent=True) == "rearm"
    assert fr.action_for("healthy", 0, resume_sent=True) is None



def test_resume_marker_outlives_the_recovery_cooldown() -> None:
    """TRDD-RJJGXPIK: the marker TTL must exceed the per-instance recovery cooldown, or the
    marker is dead code. The soonest the next rung beat can come is COOLDOWN_S after the last
    fire (every fire and decline stamps it); a TTL below that expires before the marker is ever
    read and every beat would type another `resume`. At exactly that next beat the marker must
    still be live and route to ESC-only."""
    assert sl.RESUME_EPISODE_TTL_S > fr.COOLDOWN_S
    marked = {"attempt": 1, "confirmed": True, "resume_sent": True, "resume_sent_at": 1000}
    now = 1000 + fr.COOLDOWN_S
    assert fr.gate(last_ts=1000, attempts=1, now=now) == "ok"  # the very next possible rung beat
    assert sl.resume_sent_active(marked, now) is True
    assert fr.action_for("frozen", 1, resume_sent=sl.resume_sent_active(marked, now)) == "esc_nudge"


def test_gate_ok_cooldown_crashloop() -> None:
    """First touch is ok; a too-recent attempt is cooled down; a spent attempt
    budget trips the crash-loop guard."""
    now = 1_000_000
    assert fr.gate(last_ts=None, attempts=0, now=now) == "ok"
    assert fr.gate(last_ts=now - 60, attempts=1, now=now) == "cooldown"   # 60s < COOLDOWN_S
    assert fr.gate(last_ts=now - fr.COOLDOWN_S - 1, attempts=1, now=now) == "ok"
    assert fr.gate(last_ts=now - fr.COOLDOWN_S - 1, attempts=fr.MAX_ATTEMPTS, now=now) == "crash_loop"


def test_crash_loop_wins_over_cooldown() -> None:
    """When the budget is spent AND the cooldown has elapsed, crash_loop wins —
    a looping recovery must stop and alert, never silently retry forever."""
    now = 1_000_000
    assert fr.gate(last_ts=now - fr.COOLDOWN_S - 100, attempts=fr.MAX_ATTEMPTS + 3, now=now) == "crash_loop"


def test_include_hard_frozen_never_escalates_past_esc_nudge() -> None:
    """include_hard (TRDD-56d24c02 increment 2 + TRDD-P7WU40G9, capped by TRDD-L32WC0H7 / F1
    derived 1): frozen is ESC-ONLY (no typed command, so no flood) at EVERY attempt, with or
    without include_hard — it never escalates to a kill rung (both retired), because a
    `frozen` diagnosis
    is a stall whose cause is unsettled (indistinguishable from a static retry-watchdog frame).
    dead→relaunch (an unrelated diagnosis, unaffected); healthy/unarmed stay None at ANY attempt."""
    for attempt in (0, 1, 2, 3, 4, 99):
        assert fr.action_for("frozen", attempt, include_hard=True, resume_sent=True) == "esc_nudge", attempt
        assert fr.action_for("frozen", attempt, include_hard=False, resume_sent=True) == "esc_nudge", attempt
    assert fr.action_for("dead", 0, include_hard=True) == "relaunch"
    assert fr.action_for("dead", 0) is None                    # unwired view preserved
    assert fr.action_for("healthy", 99, include_hard=True) is None
    assert fr.action_for("unarmed", 99, include_hard=True) is None
    assert fr.action_for("nonsense", 0, include_hard=True) is None


def test_frozen_never_TYPES_a_command_even_when_it_hard_restarts() -> None:
    """The invariant that kills the flood: a frozen session is NEVER sent a slash-command
    rung (no `/janitor-arm` can accumulate on a rate-limited input line), at any attempt, and
    never a process-killing rung either (TRDD-L32WC0H7 / F1). Once resume_sent is recorded it
    is ESC-only (no command at all); the one-per-episode first pass types only the bare
    `resume` (TRDD-RJJGXPIK owner directive), which is not slash-prefixed."""
    import fleet_inject as fi
    for attempt in range(fr.MAX_ATTEMPTS + 2):
        action = fr.action_for("frozen", attempt, include_hard=True, resume_sent=True)
        assert action is not None
        assert fi.action_to_command(action) is None, (attempt, action)  # never a typed command
        first = fr.action_for("frozen", attempt, include_hard=True)
        assert first is not None and not sl.is_hard_rung(first)
        assert fi.action_to_command(first) == "resume", (attempt, first)  # bare word, no "/"
    assert fr.gate(last_ts=None, attempts=fr.MAX_ATTEMPTS, now=1_000_000) == "crash_loop"


def test_injection_is_hard_only_for_frozen() -> None:
    """Hard/soft injection policy (TRDD-0GPQROC1): ESC-interrupt ONLY a frozen/retry_wedged
    target (its wedged turn never ends, so an enqueued command would never run). Every LIVE
    injectable diagnosis gets a soft enqueue that preserves in-flight work — as does
    anything unknown (fail toward not destroying work)."""
    assert fr.injection_is_hard("frozen") is True
    assert fr.injection_is_hard("retry_wedged") is True
    assert fr.injection_is_hard("cron_dead") is False
    assert fr.injection_is_hard("version_mismatch") is False
    assert fr.injection_is_hard("healthy") is False
    assert fr.injection_is_hard("nonsense") is False


def test_action_for_retry_wedged_never_escalates_to_hard_restart() -> None:
    """TRDD-WKTD5JTC advisor correction #1 — the guardrail this whole feature exists to
    hold: retry_wedged is ESC-only (esc_nudge) at EVERY attempt count, with OR without
    include_hard, and never becomes a hard/kill rung. This is the test that would go RED
    if retry_wedged were (mis)mapped through frozen's 'ladder' escalation, which used to
    reach a kill rung (since retired) at attempts>=_FROZEN_GENTLE_ATTEMPTS under
    include_hard=True."""
    for attempt in (0, 1, 2, 3, 4, 99):
        for include_hard in (False, True):
            action = fr.action_for("retry_wedged", attempt, include_hard=include_hard, resume_sent=True)
            assert action == "esc_nudge", (attempt, include_hard, action)
            first = fr.action_for("retry_wedged", attempt, include_hard=include_hard)
            assert first == "esc_nudge_resume", (attempt, include_hard, first)
            assert not sl.is_hard_rung(first)
            assert not sl.is_hard_rung(action)
