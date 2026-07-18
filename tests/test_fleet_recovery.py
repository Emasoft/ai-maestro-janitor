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


def test_frozen_gentle_recovery_is_esc_only() -> None:
    """THE FLOOD FIX (TRDD-P7WU40G9): the GENTLE recovery for a frozen (rate-limited) session is
    ESC-ONLY (`esc_nudge`) at every attempt — never a typed slash-command that would accumulate on
    the retry-blocked input line and flood. The old command-typing ladder (rearm/reload/update) is
    gone. Without `include_hard` this is the WHOLE ladder (ESC forever, then the crash-loop guard)."""
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


def test_include_hard_frozen_escalates_only_after_esc_is_exhausted() -> None:
    """include_hard (TRDD-56d24c02 increment 2 + TRDD-P7WU40G9): the first
    `_FROZEN_GENTLE_ATTEMPTS` frozen attempts are ESC-ONLY (no typed command, so no flood); ONLY
    after those does it escalate ONE rung to force_restart (kill + `claude --continue`, which
    resumes from the transcript so no work is lost) — the DEFAULT-OFF last resort. dead→relaunch;
    healthy/unarmed stay None at ANY attempt."""
    for attempt in range(fr._FROZEN_GENTLE_ATTEMPTS):          # 0,1,2 → ESC-only
        assert fr.action_for("frozen", attempt, include_hard=True) == "esc_nudge", attempt
    assert fr.action_for("frozen", fr._FROZEN_GENTLE_ATTEMPTS, include_hard=True) == "force_restart"
    assert fr.action_for("frozen", 99, include_hard=True) == "force_restart"  # clamps, no wrap
    assert fr.action_for("dead", 0, include_hard=True) == "relaunch"
    assert fr.action_for("dead", 0) is None                    # unwired view preserved
    assert fr.action_for("healthy", 99, include_hard=True) is None
    assert fr.action_for("unarmed", 99, include_hard=True) is None
    assert fr.action_for("nonsense", 0, include_hard=True) is None


def test_frozen_never_TYPES_a_command_even_when_it_hard_restarts() -> None:
    """The invariant that kills the flood: a frozen session's action is NEVER a command-typing
    rung — it is ESC-only, or (last resort) a process-killing rung that types no slash-command.
    So no `/janitor-arm` can ever accumulate on a rate-limited session's input line, at any attempt."""
    import fleet_inject as fi
    for attempt in range(fr.MAX_ATTEMPTS + 2):
        action = fr.action_for("frozen", attempt, include_hard=True)
        assert action is not None
        assert fi.action_to_command(action) is None, (attempt, action)  # never a typed command
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
