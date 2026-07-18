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


def test_action_for_per_diagnosis() -> None:
    """cron_dead re-arms, version_mismatch reloads, and the never-touch diagnoses
    (healthy/unarmed) plus the hard-restart-only one (dead) yield no typed action."""
    assert fr.action_for("cron_dead", 0) == "rearm"
    assert fr.action_for("version_mismatch", 0) == "reload"
    assert fr.action_for("healthy", 0) is None
    assert fr.action_for("unarmed", 0) is None
    assert fr.action_for("dead", 0) is None       # → hard-restart A5, not a typed command
    assert fr.action_for("nonsense", 0) is None


def test_frozen_is_esc_only_at_every_attempt() -> None:
    """THE FLOOD FIX (TRDD-P7WU40G9): a frozen session is RATE-LIMITED and sitting in Claude
    Code's retry-watchdog wait, which BUFFERS typed input. So the recovery is ESC-ONLY
    (`esc_nudge`) at EVERY attempt — never a typed slash-command that would accumulate on the
    retry-blocked input line and flood. No attempt-indexed ladder: ESC is the whole recovery,
    and the session's own rate-limited.flag → [janitor-resume] resumes the work."""
    for attempt in (-1, 0, 1, 2, 3, 99):
        assert fr.action_for("frozen", attempt) == "esc_nudge", attempt


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


def test_include_hard_only_wires_dead_never_escalates_frozen() -> None:
    """include_hard (TRDD-56d24c02 increment 2) wires `dead`→`relaunch`. It does NOT escalate a
    frozen session: since TRDD-P7WU40G9 a rate-limited (frozen) session is ESC-ONLY at every
    attempt and NEVER hard-restarts — killing a rate-limited process would discard its in-flight
    work, so the crash-loop guard pages a human instead. healthy/unarmed stay None at ANY attempt."""
    assert fr.action_for("frozen", 3, include_hard=True) == "esc_nudge"   # NO force_restart escalation
    assert fr.action_for("frozen", 99, include_hard=True) == "esc_nudge"
    assert fr.action_for("dead", 0, include_hard=True) == "relaunch"
    assert fr.action_for("dead", 0) is None                    # unwired view preserved
    assert fr.action_for("healthy", 99, include_hard=True) is None
    assert fr.action_for("unarmed", 99, include_hard=True) is None
    assert fr.action_for("nonsense", 0, include_hard=True) is None


def test_frozen_never_reaches_a_hard_rung() -> None:
    """A frozen (rate-limited) session's action is never a process-killing rung, at any attempt —
    so the daemon's `is_hard_rung` branch never fires for it and its work is never discarded. When
    ESC does not recover it within the budget, the crash-loop guard (attempts==MAX_ATTEMPTS) stops
    poking and alerts a human."""
    import session_liveness as sl
    for attempt in range(fr.MAX_ATTEMPTS + 2):
        action = fr.action_for("frozen", attempt, include_hard=True)
        assert action is not None and not sl.is_hard_rung(action)
    assert fr.gate(last_ts=None, attempts=fr.MAX_ATTEMPTS, now=1_000_000) == "crash_loop"


def test_injection_is_hard_only_for_frozen() -> None:
    """Hard/soft injection policy (TRDD-0GPQROC1): ESC-interrupt ONLY a frozen target
    (its wedged turn never ends, so an enqueued command would never run). Every LIVE
    injectable diagnosis gets a soft enqueue that preserves in-flight work — as does
    anything unknown (fail toward not destroying work)."""
    assert fr.injection_is_hard("frozen") is True
    assert fr.injection_is_hard("cron_dead") is False
    assert fr.injection_is_hard("version_mismatch") is False
    assert fr.injection_is_hard("healthy") is False
    assert fr.injection_is_hard("nonsense") is False
