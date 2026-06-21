"""Integration test for the daemon's fleet-guardian task (TRDD-324223a6, A2).

This wires the REAL policy (fleet_recovery), the REAL plan builder
(fleet_inject.build_injection) and the REAL task orchestration together; only two
things are controlled, and both for a hard reason, not convenience:

- ``gather_fleet`` is replaced with a fixed instance list — a genuinely-frozen
  claude session cannot be conjured inside a unit test.
- ``fleet_inject.fire`` is replaced with a recorder — a test MUST NOT actually
  inject ESC + /janitor-arm keystrokes into the developer's real terminals.

Everything between (which diagnosis → which action, reachable vs not, cooldown,
crash-loop give-up, healthy-resets-state) runs for real against an isolated
``JANITOR_GLOBAL_STATE_DIR``.
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


def _inst(diagnosis: str, root: str, terminal: dict) -> "fleet_scan.Instance":
    """A synthetic Instance — only diagnosis/root/terminal matter to the task."""
    return fleet_scan.Instance(
        pid=1, command="claude", tty="ttys1", project_root=root, terminal=terminal,
        diagnosis=diagnosis, recovery=None, dispatch_age_s=None, active=False,
        transcript_age_s=None,
    )


def _setup(monkeypatch, tmp_path: Path, fleet: list, *, fire: str = "1") -> list:
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))   # recovery state
    monkeypatch.setenv("JANITOR_LOG_DIR", str(tmp_path / "logs"))   # mirrors the real daemon main()
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_FLEET_RECOVERY_ENABLED", fire)
    # The whole path-resolution chain is @lru_cache'd (log_dir → janitor_root →
    # project_root) — stable in production, but it would otherwise pin the FIRST
    # test's tmp dir for the whole process. Clear the entire chain per test.
    for fn in (daemon.state.project_root, daemon.state.janitor_root,
               daemon.state.state_dir, daemon.state.log_dir):
        fn.cache_clear()
    recorded: list = []
    monkeypatch.setattr(daemon.fleet_inject, "fire", lambda plan: bool(recorded.append(plan)) or True)
    monkeypatch.setattr(daemon.fleet_scan, "gather_fleet", lambda *, now: fleet)
    return recorded


def _log(tmp_path: Path) -> str:
    # the daemon logs to JANITOR_LOG_DIR (set in _setup) → <tmp>/logs/daemon.log
    p = tmp_path / "logs" / "daemon.log"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def test_dry_run_detects_but_never_fires(tmp_path, monkeypatch) -> None:
    """With firing OFF the task logs the would-do plan but injects nothing and
    bumps no attempt counter — the detection-before-action mode."""
    fleet = [
        _inst("frozen", "/p/proj-a", {"tmux_pane": "%5"}),
        _inst("healthy", "/p/proj-b", {"tmux_pane": "%6"}),
        _inst("unarmed", "/p/proj-c", {"tmux_pane": "%7"}),
    ]
    fired = _setup(monkeypatch, tmp_path, fleet, fire="0")
    daemon.task_session_liveness()
    assert fired == []                                   # dry-run fires nothing
    assert "session-liveness:DRY would rearm" in _log(tmp_path)
    assert "proj-a" in _log(tmp_path)
    assert list((tmp_path / "recovery").glob("*.json")) == []   # no attempt persisted


def test_fire_recovers_reachable_skips_unreachable(tmp_path, monkeypatch) -> None:
    """Firing ON: a frozen tmux session and a cron-dead iTerm session are recovered
    on their own channels; a frozen session with no resolvable terminal is logged
    UNREACHABLE and not fired."""
    fleet = [
        _inst("frozen", "/p/proj-a", {"tmux_pane": "%5"}),
        _inst("cron_dead", "/p/proj-b", {"iterm_session_id": "ttys3:4C4A-9B7"}),
        _inst("frozen", "/p/proj-c", {}),               # unreachable
    ]
    fired = _setup(monkeypatch, tmp_path, fleet)
    daemon.task_session_liveness()
    assert sorted(p["channel"] for p in fired) == ["iterm", "tmux"]
    assert sorted(p["command"] for p in fired) == ["/janitor-arm", "/janitor-arm"]
    assert "UNREACHABLE" in _log(tmp_path)
    # an immediate 2nd beat is blocked by the per-instance cooldown
    fired.clear()
    daemon.task_session_liveness()
    assert fired == []


def test_crash_loop_alerts_once_then_stays_silent(tmp_path, monkeypatch) -> None:
    """A spent attempt budget (with an elapsed cooldown) trips the crash-loop guard:
    it never fires, alerts a human exactly ONCE, and stays silent thereafter."""
    fleet = [_inst("frozen", "/p/proj-x", {"tmux_pane": "%9"})]
    fired = _setup(monkeypatch, tmp_path, fleet)
    rec = tmp_path / "recovery"
    rec.mkdir(parents=True)
    sf = daemon._recovery_state_path(rec, "/p/proj-x")
    # Seed the spent budget WITH this exact session's identity (pid:tty) — otherwise
    # the identity-stamp guard treats it as a different occupant and correctly resets
    # it (which is itself covered by test_restarted_session_gets_a_fresh_budget below).
    ident = f"{fleet[0].pid}:{fleet[0].tty or ''}"
    sf.write_text(
        json.dumps({"attempts": daemon.fr.MAX_ATTEMPTS, "last_ts": 1, "identity": ident}),
        encoding="utf-8",
    )
    daemon.task_session_liveness()
    assert fired == []
    assert "GIVING UP" in _log(tmp_path)
    assert json.loads(sf.read_text(encoding="utf-8"))["alerted"] is True
    daemon.task_session_liveness()                       # 2nd beat: already alerted
    assert _log(tmp_path).count("GIVING UP") == 1


def test_recovered_instance_resets_its_attempt_budget(tmp_path, monkeypatch) -> None:
    """Once an instance is healthy again, its stale attempt counter is cleared so a
    FUTURE freeze starts with a fresh budget — never inheriting a spent one."""
    fleet = [_inst("healthy", "/p/proj-h", {"tmux_pane": "%1"})]
    _setup(monkeypatch, tmp_path, fleet)
    rec = tmp_path / "recovery"
    rec.mkdir(parents=True)
    sf = daemon._recovery_state_path(rec, "/p/proj-h")
    sf.write_text(json.dumps({"attempts": 3, "last_ts": 1}), encoding="utf-8")
    daemon.task_session_liveness()
    assert not sf.exists()


def test_restarted_session_gets_a_fresh_budget(tmp_path, monkeypatch) -> None:
    """A spent/alerted budget left by a PREVIOUS occupant of the same project dir
    (different pid:tty) must NOT be inherited by a freshly-restarted session — the new
    session did nothing wrong and gets a fresh budget, so it IS recovered (audit C3)."""
    fleet = [_inst("frozen", "/p/proj-r", {"tmux_pane": "%2"})]   # identity 1:ttys1
    fired = _setup(monkeypatch, tmp_path, fleet)
    rec = tmp_path / "recovery"
    rec.mkdir(parents=True)
    sf = daemon._recovery_state_path(rec, "/p/proj-r")
    sf.write_text(
        json.dumps({"attempts": daemon.fr.MAX_ATTEMPTS, "last_ts": 1,
                    "alerted": True, "identity": "99999:ttysOLD"}),  # a vanished session
        encoding="utf-8",
    )
    daemon.task_session_liveness()
    assert len(fired) == 1                      # recovered, NOT refused by a stale budget
    st = json.loads(sf.read_text(encoding="utf-8"))
    assert st["identity"] == "1:ttys1"          # budget rebound to the NEW session
    assert st["attempts"] == 1                  # fresh budget (1st attempt), not the old MAX


def test_corrupt_state_file_does_not_crash_the_beat(tmp_path, monkeypatch) -> None:
    """A valid-JSON-but-not-an-object state file (external tampering) degrades to a
    fresh budget for that instance instead of crashing the whole beat (audit C4)."""
    fleet = [_inst("frozen", "/p/proj-c", {"tmux_pane": "%3"})]
    fired = _setup(monkeypatch, tmp_path, fleet)
    rec = tmp_path / "recovery"
    rec.mkdir(parents=True)
    sf = daemon._recovery_state_path(rec, "/p/proj-c")
    sf.write_text("[1, 2, 3]", encoding="utf-8")   # valid JSON, NOT a dict
    daemon.task_session_liveness()                 # must not raise
    assert len(fired) == 1                          # treated as fresh → recovered
