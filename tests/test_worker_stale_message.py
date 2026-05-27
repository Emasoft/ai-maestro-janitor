"""Tests for `build_worker_stale_message` (issue #9 fix).

The original heartbeat message for both `marketplace-refresh` and
`user-plugins-update` said "daemon may be stuck" even when the daemon
process was healthy (only a worker subroutine had wedged) AND recommended
inspecting `~/.claude/janitor-global-state/daemon.log` — a file the daemon
has never written. This forced users to investigate the wrong layer and
to chase a non-existent log.

`build_worker_stale_message` distinguishes the three legitimate states:

* daemon process alive + heartbeat fresh → "worker has wedged" wording
  AND PID + heartbeat-age context (so the user can verify against `ps`)
* daemon process dead or heartbeat stale → "daemon process is not
  responding" wording
* `daemon.log` only mentioned when it actually exists on disk
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))


@pytest.fixture
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated global state dir per test — same convention as test_global_state."""
    d = tmp_path / "janitor-global-state"
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(d))
    for mod in ("global_state",):
        if mod in sys.modules:
            del sys.modules[mod]
    return d


def _gs():
    import global_state  # type: ignore[import-not-found]
    return global_state


def _arm_alive_daemon(gs, hb_age_s: int = 5) -> None:
    """Write daemon.pid (using THIS pytest PID — guaranteed alive) and a
    fresh daemon.heartbeat.ts that's `hb_age_s` seconds old."""
    gs.init_global_state()
    gs.write_daemon_pid(os.getpid())
    gs.write_heartbeat(int(time.time()) - hb_age_s)


def _arm_dead_daemon(gs) -> None:
    """Write daemon.pid pointing at a definitely-not-running PID."""
    gs.init_global_state()
    # PID 0 is sentinel for swapper on Unix — kill(0, 0) raises ESRCH for
    # any unprivileged user. Combined with daemon_pid()'s `not raw.isdigit()`
    # check we'd have to bypass the helper; instead use an absurdly high PID
    # that cannot belong to anything on a fresh test sandbox.
    gs.write_daemon_pid(2**31 - 1)
    gs.write_heartbeat(int(time.time()))  # heartbeat fresh but PID dead


# ─── daemon alive + worker stuck → "worker has wedged" wording ───────────


class TestDaemonAliveWorkerWedged:
    """When the daemon process is healthy but a worker is stale, the
    message must NOT say 'daemon may be stuck' — it must distinguish the
    layers so the user doesn't go check the wrong process."""

    def test_alive_daemon_message_says_daemon_is_alive(self, state_dir: Path) -> None:
        gs = _gs()
        _arm_alive_daemon(gs, hb_age_s=5)
        msg = gs.build_worker_stale_message(
            worker_tag="marketplace-refresh",
            worker_action="refreshed global marketplaces",
            age_s=2600,
            cadence_s=1200,
        )
        assert "daemon process is alive" in msg, msg
        assert "daemon may be stuck" not in msg, msg

    def test_alive_daemon_message_includes_pid(self, state_dir: Path) -> None:
        gs = _gs()
        _arm_alive_daemon(gs, hb_age_s=5)
        msg = gs.build_worker_stale_message(
            worker_tag="marketplace-refresh",
            worker_action="refreshed global marketplaces",
            age_s=2600,
            cadence_s=1200,
        )
        assert f"PID {os.getpid()}" in msg, msg

    def test_alive_daemon_message_includes_heartbeat_age(self, state_dir: Path) -> None:
        gs = _gs()
        _arm_alive_daemon(gs, hb_age_s=42)
        msg = gs.build_worker_stale_message(
            worker_tag="marketplace-refresh",
            worker_action="refreshed global marketplaces",
            age_s=2600,
            cadence_s=1200,
        )
        assert "last heartbeat" in msg, msg
        # Age can be 42s or 43s depending on test-runtime slop; check the band.
        assert ("42s ago" in msg) or ("43s ago" in msg), msg

    def test_alive_daemon_message_says_worker_wedged(self, state_dir: Path) -> None:
        gs = _gs()
        _arm_alive_daemon(gs)
        msg = gs.build_worker_stale_message(
            worker_tag="marketplace-refresh",
            worker_action="refreshed global marketplaces",
            age_s=2600,
            cadence_s=1200,
        )
        assert "marketplace-refresh worker has likely wedged" in msg, msg


# ─── daemon dead → "daemon process is not responding" wording ────────────


class TestDaemonDeadOrStale:
    """When the daemon process itself is dead, the message must SAY so
    (not blame the worker)."""

    def test_dead_daemon_message_says_process_not_responding(self, state_dir: Path) -> None:
        gs = _gs()
        _arm_dead_daemon(gs)
        msg = gs.build_worker_stale_message(
            worker_tag="marketplace-refresh",
            worker_action="refreshed global marketplaces",
            age_s=2600,
            cadence_s=1200,
        )
        assert "daemon process itself is not responding" in msg, msg
        assert "daemon process is alive" not in msg, msg

    def test_no_pid_file_treated_as_dead_daemon(self, state_dir: Path) -> None:
        """No pid file at all → message uses the dead-daemon wording."""
        gs = _gs()
        gs.init_global_state()  # state dir exists but no daemon.pid written
        msg = gs.build_worker_stale_message(
            worker_tag="user-plugins-update",
            worker_action="swept user-scope plugins",
            age_s=8000,
            cadence_s=3600,
        )
        assert "daemon process itself is not responding" in msg, msg

    def test_stale_heartbeat_treated_as_dead_daemon(self, state_dir: Path) -> None:
        """Even with a live PID, a heartbeat older than DEFAULT_DAEMON_STALE_SECONDS
        means the daemon is wedged at the process level → dead-daemon wording."""
        gs = _gs()
        gs.init_global_state()
        gs.write_daemon_pid(os.getpid())
        # Set heartbeat 1 second past the staleness window (default 1800s).
        gs.write_heartbeat(int(time.time()) - (gs.DEFAULT_DAEMON_STALE_SECONDS + 1))
        msg = gs.build_worker_stale_message(
            worker_tag="marketplace-refresh",
            worker_action="refreshed global marketplaces",
            age_s=2600,
            cadence_s=1200,
        )
        assert "daemon process itself is not responding" in msg, msg


# ─── daemon.log conditional reference ────────────────────────────────────


class TestDaemonLogReference:
    """The 'Inspect: <path>' clause must only appear when the log exists."""

    def test_no_log_file_no_inspect_clause(self, state_dir: Path) -> None:
        """The repro: daemon.log doesn't exist (the common case today)."""
        gs = _gs()
        _arm_alive_daemon(gs)
        msg = gs.build_worker_stale_message(
            worker_tag="marketplace-refresh",
            worker_action="refreshed global marketplaces",
            age_s=2600,
            cadence_s=1200,
        )
        assert "Inspect:" not in msg, msg
        assert "daemon.log" not in msg, msg

    def test_log_file_exists_inspect_clause_appears(self, state_dir: Path) -> None:
        """When the daemon DOES write a log, the inspect-clause comes back."""
        gs = _gs()
        _arm_alive_daemon(gs)
        log_path = state_dir / "daemon.log"
        log_path.write_text("some log line\n", encoding="utf-8")
        msg = gs.build_worker_stale_message(
            worker_tag="marketplace-refresh",
            worker_action="refreshed global marketplaces",
            age_s=2600,
            cadence_s=1200,
        )
        assert f"Inspect: {log_path}" in msg, msg


# ─── message-shape invariants ────────────────────────────────────────────


class TestMessageShape:
    """Per-call invariants that must hold regardless of daemon state."""

    def test_worker_tag_appears_in_brackets(self, state_dir: Path) -> None:
        gs = _gs()
        _arm_alive_daemon(gs)
        msg = gs.build_worker_stale_message(
            worker_tag="marketplace-refresh",
            worker_action="refreshed global marketplaces",
            age_s=2600,
            cadence_s=1200,
        )
        assert msg.startswith("[marketplace-refresh]"), msg

    def test_worker_action_appears(self, state_dir: Path) -> None:
        gs = _gs()
        _arm_alive_daemon(gs)
        msg = gs.build_worker_stale_message(
            worker_tag="marketplace-refresh",
            worker_action="refreshed global marketplaces",
            age_s=2600,
            cadence_s=1200,
        )
        assert "refreshed global marketplaces" in msg, msg

    def test_restart_clause_always_present(self, state_dir: Path) -> None:
        gs = _gs()
        _arm_alive_daemon(gs)
        msg = gs.build_worker_stale_message(
            worker_tag="marketplace-refresh",
            worker_action="refreshed global marketplaces",
            age_s=2600,
            cadence_s=1200,
        )
        assert "Restart: kill" in msg, msg
        assert "daemon.pid" in msg, msg

    def test_age_converted_to_minutes(self, state_dir: Path) -> None:
        gs = _gs()
        _arm_alive_daemon(gs)
        msg = gs.build_worker_stale_message(
            worker_tag="marketplace-refresh",
            worker_action="refreshed global marketplaces",
            age_s=2600,  # 43 min 20 s → ~43 min
            cadence_s=1200,
        )
        assert "~43 min" in msg, msg

    def test_cadence_appears(self, state_dir: Path) -> None:
        gs = _gs()
        _arm_alive_daemon(gs)
        msg = gs.build_worker_stale_message(
            worker_tag="marketplace-refresh",
            worker_action="refreshed global marketplaces",
            age_s=2600,
            cadence_s=1200,
        )
        assert "cadence 1200s" in msg, msg
