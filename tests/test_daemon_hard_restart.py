"""Integration tests for the A5 hard-restart wiring (TRDD-56d24c02 increment 2).

`relaunch` (rung 5) is the only hard-restart rung left: the two kill rungs
(force_restart, resurrect) were RETIRED — TRDD-56d24c02, executed by
TRDD-V07NFXS9 — because `fleet_recovery.action_for` had capped `frozen` at
`esc_nudge` unconditionally since TRDD-L32WC0H7 F1, so nothing could ever route
to them. Same philosophy as test_daemon_session_liveness.py: the REAL policy
(fleet_recovery.action_for), the REAL plan builder (fleet_restart) and the REAL
beat orchestration + audit run together against an isolated
``JANITOR_GLOBAL_STATE_DIR``. The fleet is passed through the beat's explicit
``fleet=`` test seam (real Instance rows — a genuinely dead claude cannot be
conjured in a unit test). Relaunch never kills a process, so no test here ever
touches a real one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "oauth_rotator"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import daemon  # type: ignore[import-not-found]  # noqa: E402
import fleet_scan  # type: ignore[import-not-found]  # noqa: E402

# A real captured/anonymized IDLE frame — an empty input field, no wedge, no dialog.
# Needed only by the gentle esc_nudge path (the pane-policy read); the hard rungs never
# reach it.
_IDLE_PANE = (
    _PROJECT_ROOT / "tests" / "fixtures" / "pane_frames" / "synthetic-idle-empty-field.txt"
).read_text(encoding="utf-8")


def _inst(
    diagnosis: str,
    root: str,
    terminal: dict,
    *,
    pid: int = 1,
    command: str = "claude",
    active: bool = False,
) -> "fleet_scan.Instance":
    """A synthetic Instance carrying the fields the hard-restart gates read."""
    return fleet_scan.Instance(
        pid=pid, command=command, tty="ttys1", project_root=root, terminal=terminal,
        diagnosis=diagnosis, recovery=None, dispatch_age_s=None, active=active,
        transcript_age_s=None,
    )


def _setup(monkeypatch, tmp_path: Path, *, fire: str = "1", hard: str | None = None) -> list:
    """Isolate global state + logs; recorder on the GENTLE injector so a test can
    prove the hard path never routes through it. The hard executor needs no seam:
    every test keeps it un-executable by gate (flag off, or killable False)."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("JANITOR_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_FLEET_RECOVERY_ENABLED", fire)
    if hard is None:
        monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_FLEET_HARD_RESTART_ENABLED", raising=False)
    else:
        monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_FLEET_HARD_RESTART_ENABLED", hard)
    for fn in (daemon.state.project_root, daemon.state.janitor_root,
               daemon.state.state_dir, daemon.state.log_dir):
        fn.cache_clear()
    # The gentle esc_nudge path reads the pane back through the policy table before
    # typing; an unreadable pane (the sandbox's real posture) reads as REFUSED, which
    # would make every frozen/esc_nudge test fail for a reason unrelated to what it
    # tests. Pin it to a real idle frame — same fixture test_daemon_session_liveness.py
    # uses. The hard rungs never read this.
    monkeypatch.setattr(daemon.fleet_inject.terminal_trigger, "read_pane_text", lambda rt: _IDLE_PANE)
    recorded: list = []
    monkeypatch.setattr(
        daemon.fleet_inject, "fire", lambda plan: bool(recorded.append(plan)) or True
    )
    return recorded


def _log(tmp_path: Path) -> str:
    p = tmp_path / "logs" / "daemon.log"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _audit_records(tmp_path: Path) -> list[dict]:
    p = tmp_path / "recovery-audit.ndjson"
    if not p.exists():
        return []
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _state(tmp_path: Path, root: str) -> dict:
    sf = daemon._recovery_state_path(tmp_path / "recovery", root)
    return json.loads(sf.read_text(encoding="utf-8")) if sf.exists() else {}


def test_dead_relaunch_is_dry_run_by_default(tmp_path, monkeypatch) -> None:
    """A dead instance now reaches rung 5, but DEFAULT-OFF means DRY_RUN: the plan is
    built and logged, nothing fires, and the attempt is still consumed (so a
    permanently-disabled rung walks to the crash-loop alert instead of logging forever)."""
    root = str(tmp_path / "proj")
    gentle = _setup(monkeypatch, tmp_path)  # hard flag ABSENT → default-off
    daemon.task_session_liveness(fleet=[_inst("dead", root, {"tmux_pane": "%7"})])
    assert "DRY_RUN:relaunch" in _log(tmp_path)
    assert gentle == []  # never routed through the gentle injector
    assert _state(tmp_path, root)["attempts"] == 1  # dry-run consumes the attempt
    rec = _audit_records(tmp_path)
    assert [r["outcome"] for r in rec] == ["dry_run"]
    assert rec[0]["rung"] == "relaunch" and rec[0]["channel"] == "tmux"


def test_dead_with_no_channel_is_logged_unreachable(tmp_path, monkeypatch) -> None:
    """No pane → relaunch cannot type anywhere, and `dead` has no other rung to fall back
    to (the two kill rungs are retired). No ATTEMPT consumed (nothing was
    tried, so the crash-loop budget stays honest) — but the decision IS stamped with a
    cooldown + audit signature (F9), so an instance we can never poke stops being
    re-decided and re-audited on every 120 s beat."""
    root = str(tmp_path / "proj")
    _setup(monkeypatch, tmp_path, hard="1")  # even ENABLED: no channel → no action
    daemon.task_session_liveness(fleet=[_inst("dead", root, {})])
    assert "UNREACHABLE" in _log(tmp_path)
    st = _state(tmp_path, root)
    assert "attempts" not in st                          # no budget spent
    assert st["last_ts"] and st["last_audit"] == "unreachable:relaunch"
    assert [r["outcome"] for r in _audit_records(tmp_path)] == ["unreachable"]


def test_frozen_exhausted_stays_esc_nudge_then_crash_loop(tmp_path, monkeypatch) -> None:
    """TRDD-L32WC0H7 F1: `frozen` is CAPPED at esc_nudge at every attempts value —
    exhaustion (attempt 3 -> 4) never escalates to a kill rung (both retired — see the
    module docstring), it just trips the crash-loop guard and pages a human ONCE, same
    as any other capped rung."""
    root = str(tmp_path / "proj")
    gentle = _setup(monkeypatch, tmp_path)  # hard flag off; irrelevant to esc_nudge anyway
    rec_dir = tmp_path / "recovery"
    rec_dir.mkdir(parents=True, exist_ok=True)
    sf = daemon._recovery_state_path(rec_dir, root)
    sf.write_text(json.dumps({"attempts": 3, "identity": "1:ttys1"}), encoding="utf-8")
    frozen = _inst("frozen", root, {"tmux_pane": "%7"})
    daemon.task_session_liveness(fleet=[frozen])
    assert "DRY_RUN:relaunch" not in _log(tmp_path)
    assert len(gentle) == 1  # esc_nudge routed through the GENTLE injector, not a hard rung
    assert _state(tmp_path, root)["attempts"] == 4
    daemon.task_session_liveness(fleet=[frozen])  # budget spent → give up + alert once
    assert "GIVING UP" in _log(tmp_path)
    outcomes = [r["outcome"] for r in _audit_records(tmp_path)]
    assert outcomes == ["fired", "declined_crash_loop"]


def test_frozen_never_reaches_the_hard_restart_plan(tmp_path, monkeypatch) -> None:
    """`_hard_restart_plan` answers ONLY `dead` (rung 5, relaunch); a `frozen` instance —
    which used to escalate to the now-retired kill rungs — gets None, same as any other
    diagnosis `_hard_restart_plan` was never meant to handle."""
    root = str(tmp_path / "proj")
    _setup(monkeypatch, tmp_path)
    assert daemon._hard_restart_plan(_inst("frozen", root, {"tmux_pane": "%9"})) is None


def _record_identity(root: str, ident: dict) -> None:
    """Write the pane identity a session records at start (on-session-start.py)."""
    d = Path(root) / ".janitor" / "state"
    d.mkdir(parents=True, exist_ok=True)
    (d / "terminal-identity.json").write_text(json.dumps(ident), encoding="utf-8")


def test_live_pane_still_wins_over_a_stale_recording(tmp_path, monkeypatch) -> None:
    """The recording is a FALLBACK, not a substitute: when live resolves, live is used.

    Otherwise a pane that moved or was recycled since session start would be typed into
    on the strength of a stale file.
    """
    root = str(tmp_path / "proj")
    _setup(monkeypatch, tmp_path)
    _record_identity(root, {"tmux_pane": "%9"})

    plan = daemon._hard_restart_plan(_inst("dead", root, {"tmux_pane": "%1"}))

    assert plan is not None and plan["rung"] == "relaunch"
    # the pane is the `-t` target of each send-keys step
    targets = [step[step.index("-t") + 1] for step in plan["steps"] if "-t" in step]
    assert targets and set(targets) == {"%1"}      # the LIVE pane
    assert "%9" not in str(plan["steps"])          # never the stale recording


def test_no_diagnosis_ever_routes_to_a_kill_rung() -> None:
    """The guard on the guard (TRDD-L32WC0H7 F1 / TRDD-V07NFXS9). `action_for` no
    longer names a kill rung as a return value at all — both were RETIRED, not just
    capped. This test fails loudly the moment someone reintroduces one.

    Diagnoses HARDCODED below: `action_for` branches on string literals and exports
    no enum, and the full set lives one layer up, in
    `session_liveness.diagnose_instance`'s precedence table (`unarmed`,
    `server_owned`, `dead`, `healthy`, `retry_wedged`, `frozen`, `version_mismatch`,
    `cron_dead` — verified against that function 2026-09-04). ADD ANY NEW DIAGNOSIS
    HERE — one missing from this tuple is silently unpinned, which is the exact
    failure this test exists to prevent.
    """
    _all_diagnoses = ("healthy", "dead", "frozen", "retry_wedged", "version_mismatch",
                       "cron_dead", "unarmed", "server_owned")
    # The old (removed) escalation was attempt-dependent — it fired once `attempts`
    # crossed the crash-loop threshold. Sweep a range spanning well past it so a
    # reintroduced attempt-gated escalation can't hide at an attempts value this
    # test doesn't check.
    # BOTH values of `include_hard`: sweeping only True would miss a route added under
    # include_hard=False, and "the kill is behind the hard gate" is an assumption about the
    # very code this test exists to stop someone changing.
    for diagnosis in _all_diagnoses:
        for attempts in (0, 1, 3, 4, 9, 100):
            for hard in (True, False):
                action = daemon.fr.action_for(diagnosis, attempts, include_hard=hard)
                assert action not in ("force_restart", "resurrect"), (diagnosis, attempts, hard, action)
    assert daemon.fr.action_for("frozen", 9, include_hard=True) == "esc_nudge"
