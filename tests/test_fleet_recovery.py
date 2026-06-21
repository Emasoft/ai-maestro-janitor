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


def test_frozen_walks_the_ladder_then_clamps() -> None:
    """A frozen session escalates rearm → reload → update across attempts and then
    stays at the strongest gentle rung (never wraps to a weaker no-op)."""
    assert fr.action_for("frozen", 0) == "rearm"
    assert fr.action_for("frozen", 1) == "reload"
    assert fr.action_for("frozen", 2) == "update"
    assert fr.action_for("frozen", 3) == "update"   # clamps, doesn't wrap
    assert fr.action_for("frozen", 99) == "update"
    assert fr.action_for("frozen", -1) == "rearm"   # defensive lower clamp


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
