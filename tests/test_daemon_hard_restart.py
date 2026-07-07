"""Integration tests for the A5 hard-restart wiring (TRDD-56d24c02 increment 2).

Same philosophy as test_daemon_session_liveness.py: the REAL policy
(fleet_recovery.action_for include_hard), the REAL plan builders (fleet_restart)
and the REAL beat orchestration + audit run together against an isolated
``JANITOR_GLOBAL_STATE_DIR``. The fleet is passed through the beat's explicit
``fleet=`` test seam (real Instance rows — a genuinely dead/wedged claude cannot
be conjured in a unit test), and NO test ever runs with BOTH the hard opt-in
enabled AND a killable target: execution is proven blocked by each gate
(DEFAULT-OFF dry-run, is_killable refusal) BEFORE the kill line is reachable, so
no process is ever touched.
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
    """No pane → relaunch cannot type anywhere; no resurrect fallback for `dead`
    (resurrect KILLS and is_killable is frozen-only). Nothing consumed, audit says why."""
    root = str(tmp_path / "proj")
    _setup(monkeypatch, tmp_path, hard="1")  # even ENABLED: no channel → no action
    daemon.task_session_liveness(fleet=[_inst("dead", root, {})])
    assert "UNREACHABLE" in _log(tmp_path)
    assert _state(tmp_path, root) == {}  # no attempt consumed
    assert [r["outcome"] for r in _audit_records(tmp_path)] == ["unreachable"]


def test_frozen_exhausted_escalates_to_force_restart_then_crash_loop(tmp_path, monkeypatch) -> None:
    """The reconciled ladder: attempts 0-2 stay gentle; attempt 3 is the ONE hard
    attempt (force_restart, dry-run here); attempt 4 trips the crash-loop guard and
    pages a human ONCE — the TRDD's bounded-storm invariant, end to end."""
    root = str(tmp_path / "proj")
    _setup(monkeypatch, tmp_path)  # hard flag off → dry-run
    rec_dir = tmp_path / "recovery"
    rec_dir.mkdir(parents=True, exist_ok=True)
    sf = daemon._recovery_state_path(rec_dir, root)
    sf.write_text(json.dumps({"attempts": 3, "identity": "1:ttys1"}), encoding="utf-8")
    frozen = _inst("frozen", root, {"tmux_pane": "%7"})
    daemon.task_session_liveness(fleet=[frozen])
    assert "DRY_RUN:force_restart" in _log(tmp_path)
    assert _state(tmp_path, root)["attempts"] == 4
    daemon.task_session_liveness(fleet=[frozen])  # budget spent → give up + alert once
    assert "GIVING UP" in _log(tmp_path)
    outcomes = [r["outcome"] for r in _audit_records(tmp_path)]
    assert outcomes == ["dry_run", "declined_crash_loop"]


def test_frozen_force_restart_falls_back_to_resurrect_without_a_pane(tmp_path, monkeypatch) -> None:
    """No pane channel on a frozen-exhausted instance → the plan escalates to rung 7
    resurrect (the documented build_force_restart→None fallback) — still dry-run."""
    root = str(tmp_path / "proj")
    _setup(monkeypatch, tmp_path)
    rec_dir = tmp_path / "recovery"
    rec_dir.mkdir(parents=True, exist_ok=True)
    daemon._recovery_state_path(rec_dir, root).write_text(
        json.dumps({"attempts": 3, "identity": "1:ttys1"}), encoding="utf-8"
    )
    daemon.task_session_liveness(fleet=[_inst("frozen", root, {})])
    assert "DRY_RUN:resurrect" in _log(tmp_path)
    rec = _audit_records(tmp_path)
    assert rec[0]["rung"] == "resurrect" and rec[0]["channel"] == "spawn"


def test_enabled_but_not_killable_is_refused_before_any_kill(tmp_path, monkeypatch) -> None:
    """Gate order proof with the opt-in ON: a non-claude cmdline makes is_killable
    refuse, so fire_restart returns REFUSED before the kill line — the second
    independent gate working even when a wrong diagnosis somehow reached a kill rung.

    Fixture subtlety (learned from this test's own first run): is_killable's
    claude-check is SUBSTRING-based, so the command must not contain 'claude'
    anywhere — 'not-claude.py' would (correctly, per the check's contract) count
    as a claude process. pid=0 is a second refusal (pid<=0) so even a regression
    of the cmdline check cannot reach os.kill from this test."""
    root = str(tmp_path / "proj")
    _setup(monkeypatch, tmp_path, hard="1")
    rec_dir = tmp_path / "recovery"
    rec_dir.mkdir(parents=True, exist_ok=True)
    daemon._recovery_state_path(rec_dir, root).write_text(
        # identity must match pid=0 below or the pre-seeded budget is (correctly)
        # discarded as a stale previous occupant and the ladder restarts gentle.
        json.dumps({"attempts": 3, "identity": "0:ttys1"}), encoding="utf-8"
    )
    daemon.task_session_liveness(
        fleet=[_inst("frozen", root, {"tmux_pane": "%7"}, pid=0, command="python3 rotator.py")]
    )
    assert "REFUSED:not-killable:force_restart" in _log(tmp_path)
    assert [r["outcome"] for r in _audit_records(tmp_path)] == ["refused"]


def test_active_instance_is_never_a_hard_target(tmp_path, monkeypatch) -> None:
    """Belt-and-suspenders: even if an ACTIVE (transcript-advancing) instance were
    mis-diagnosed frozen, is_killable(active=True) refuses the kill — the user's
    working session survives a diagnosis bug. (Upstream, diagnose_instance would
    classify it healthy and it would never get here at all.)"""
    root = str(tmp_path / "proj")
    _setup(monkeypatch, tmp_path, hard="1")
    rec_dir = tmp_path / "recovery"
    rec_dir.mkdir(parents=True, exist_ok=True)
    daemon._recovery_state_path(rec_dir, root).write_text(
        json.dumps({"attempts": 3, "identity": "1:ttys1"}), encoding="utf-8"
    )
    daemon.task_session_liveness(
        fleet=[_inst("frozen", root, {"tmux_pane": "%7"}, active=True)]
    )
    assert "REFUSED:not-killable" in _log(tmp_path)
    assert [r["outcome"] for r in _audit_records(tmp_path)] == ["refused"]
