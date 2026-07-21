"""ONE DAEMON PER HOST — the janitor daemon steps aside for a live ai-maestro server.

TRDD-5ZVS1DDP / ARCHITECTURE §7.2. Owner directive 2026-07-21: *"when the ai-maestro
server is running, the daemon process must stop, and resume only when the ai-maestro
server is not running anymore. only one daemon can exist at the same time in the host"* —
because two daemons *"will conflict and write at the same time in the same files,
corrupting them.. not to mention launching chores twice"*.

Rev 4 already made the janitor YIELD its five absorbed chores to a live server. That was
chore-level and not enough: the daemon stayed up, kept the singleton flock, kept its OS
keepalive, and kept running everything outside the absorbed set. These tests pin the
process-level rule that replaces it, and — more importantly — the two ways it can go
wrong quietly:

  * a bare exit gets relaunched by launchd `KeepAlive`/systemd `Restart=always` within 30s,
    so "stopping" becomes a permanent thrash AGAINST the live server;
  * a session's heartbeat re-spawns the daemon seconds after it exits, restoring the exact
    two-owner condition the exit was meant to remove.

Detection is by FILE only (the server is "wherever the user installs ai-maestro", run
under pm2), so every test here drives `~/.aimaestro/server-liveness.json` via the
`JANITOR_AIMAESTRO_LIVENESS_FILE` override rather than any process or path.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import global_state as gs  # noqa: E402
import harness_backend  # noqa: E402
import state  # noqa: E402


@pytest.fixture
def iso(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict]:
    """Isolate HOME, the project, and the global-state dir so nothing touches the real fleet."""
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    (project / ".janitor" / "state").mkdir(parents=True)
    gdir = tmp_path / "gs"
    gdir.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(gdir))
    monkeypatch.delenv("AIMAESTRO_AGENT", raising=False)
    monkeypatch.delenv("THIS_IS_AIMAESTRO", raising=False)
    monkeypatch.delenv("AMP_AGENT_ID", raising=False)
    monkeypatch.delenv("AID_AUTH", raising=False)
    for cached in (state.project_root, state.janitor_root, state.state_dir, state.log_dir):
        cached.cache_clear()
    yield {"home": home, "project": project, "gdir": gdir, "tmp": tmp_path}
    for cached in (state.project_root, state.janitor_root, state.state_dir, state.log_dir):
        cached.cache_clear()


def _write_liveness(path: Path, *, age_s: int = 0) -> None:
    """Write a server-liveness file `age_s` seconds old (0 = fresh)."""
    path.write_text(
        json.dumps({"ts": int(time.time()) - age_s, "pid": 4242, "capabilities": []}),
        encoding="utf-8",
    )


# --------------------------------------------------------------------------- #
# The discriminator — file only, and STALE must not count as "running"
# --------------------------------------------------------------------------- #


def test_a_fresh_liveness_file_means_the_server_owns_the_host(iso: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole handshake is one file. No process name, no install path — the server is
    "wherever the user installs ai-maestro" and pm2-supervised, so a file is the only
    identity either side gets."""
    live = iso["tmp"] / "server-liveness.json"
    monkeypatch.setenv("JANITOR_AIMAESTRO_LIVENESS_FILE", str(live))

    _write_liveness(live)
    assert harness_backend.server_is_alive() is True


def test_a_STALE_liveness_file_does_NOT_mean_the_server_owns_the_host(iso: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """A crashed server leaves its last file on disk forever. If stale counted as running,
    the janitor daemon would stay permanently exited and the host would be left with NO
    daemon at all — strictly worse than the two-daemon case this feature prevents."""
    live = iso["tmp"] / "server-liveness.json"
    monkeypatch.setenv("JANITOR_AIMAESTRO_LIVENESS_FILE", str(live))

    _write_liveness(live, age_s=harness_backend.LIVENESS_STALE_AFTER_S + 30)
    assert harness_backend.server_is_alive() is False


def test_an_absent_liveness_file_means_the_janitor_owns_the_host(iso: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """The safe default: no evidence of a server ⇒ the janitor is the host daemon."""
    monkeypatch.setenv("JANITOR_AIMAESTRO_LIVENESS_FILE", str(iso["tmp"] / "nope.json"))
    assert harness_backend.server_is_alive() is False


# --------------------------------------------------------------------------- #
# No session may resurrect the daemon the server displaced
# --------------------------------------------------------------------------- #


def test_sessions_REFUSE_to_spawn_the_daemon_while_a_server_is_live(iso: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """THE test that makes the exit stick.

    Every heartbeat fire calls `ensure_daemon_running()`. Without this guard the daemon
    that just exited for "server-owns-host" is respawned within one heartbeat by any of
    the (potentially many) armed sessions, and the two-owner condition returns in seconds
    — the exit would be theatre."""
    live = iso["tmp"] / "server-liveness.json"
    monkeypatch.setenv("JANITOR_AIMAESTRO_LIVENESS_FILE", str(live))
    _write_liveness(live)

    assert gs.ensure_daemon_running() is False, "a live server must veto the spawn"
    assert gs.daemon_pid() is None, "nothing may have been spawned"


def test_the_refusal_does_NOT_count_toward_the_crash_loop_breaker(iso: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """Stepping aside is normal, not evidence the daemon cannot start.

    If it counted, a server running for a while would trip the breaker through ordinary
    heartbeats, and then — once the server stopped and a spawn were finally legitimate —
    the breaker would suppress it. The host would end up with no daemon precisely when it
    needs one, for a reason nothing on screen explains."""
    live = iso["tmp"] / "server-liveness.json"
    monkeypatch.setenv("JANITOR_AIMAESTRO_LIVENESS_FILE", str(live))
    _write_liveness(live)

    before = gs.recent_spawn_count()
    for _ in range(12):
        gs.ensure_daemon_running()
    assert gs.recent_spawn_count() == before, "a server-owns-host refusal is not a spawn attempt"
    assert gs.crash_loop_active() is False, "the breaker must not trip on normal refusals"


def test_the_daemon_becomes_spawnable_again_the_moment_liveness_goes_stale(iso: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """Resumption needs no new mechanism: the per-session heartbeat is the resurrection
    path, which is exactly why the exit is allowed to drop the OS keepalive."""
    live = iso["tmp"] / "server-liveness.json"
    monkeypatch.setenv("JANITOR_AIMAESTRO_LIVENESS_FILE", str(live))
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_DAEMON_ENABLED", "false")  # stop at the enable gate, don't fork

    _write_liveness(live)
    assert gs.ensure_daemon_running() is False  # vetoed by the server

    live.unlink()
    # Now it gets PAST the server veto and is stopped only by the explicit enable knob —
    # proving the server guard is no longer the thing blocking it.
    assert gs.ensure_daemon_running() is False
    assert gs._server_owns_host() is False, "with liveness gone, the host is the janitor's again"


def test_a_broken_liveness_probe_FAILS_OPEN_and_keeps_the_daemon(iso: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """A host with no daemon because a probe threw is unguarded; a host with a redundant
    daemon is merely wasteful and is covered by the shared file locks. So the failure
    direction is not symmetric — an exception must never evict the janitor."""
    monkeypatch.setattr(harness_backend, "server_is_alive", lambda **_: (_ for _ in ()).throw(RuntimeError("boom")))
    assert gs._server_owns_host() is False


# --------------------------------------------------------------------------- #
# The exit must not be undone by the OS supervisor
# --------------------------------------------------------------------------- #


def test_server_owns_host_exit_drops_the_OS_keepalive() -> None:
    """launchd `KeepAlive: true` + `ThrottleInterval: 30` and systemd `Restart=always`
    relaunch a bare exit every 30 s, forever. So "stop" must uninstall the keepalive, or
    the daemon spawn-exit-thrashes against the live server and floods its own log.

    Asserted on the source because the alternative is spawning a real supervised daemon in
    a unit test. The pairing with `kill-switch` is the point: both are deliberate stops,
    and the same branch must cover both."""
    body = (ROOT / "scripts" / "daemon.py").read_text(encoding="utf-8")
    assert 'exit_reason in ("kill-switch", "server-owns-host")' in body, (
        "the keepalive teardown must cover the server-owns-host exit, not only the kill-switch"
    )
    assert 'exit_reason = "server-owns-host"' in body


def test_the_server_check_is_ordered_after_kill_switch_but_before_maintenance() -> None:
    """Order is load-bearing. AFTER the kill-switch, so a human stop still wins and can
    still fleet-broadcast. BEFORE maintenance/pause, because those branches keep the
    daemon ALIVE and idling — and an idling daemon still holds the singleton flock and
    keeps its OS keepalive armed, which IS the two-owner condition wearing a quiet hat."""
    body = (ROOT / "scripts" / "daemon.py").read_text(encoding="utf-8")
    kill = body.index('exit_reason = "kill-switch"')
    server = body.index('exit_reason = "server-owns-host"')
    maint = body.index("if gs.maintenance_mode_present():", kill)
    assert kill < server < maint, "kill-switch → server-owns-host → maintenance"


def test_daemon_still_imports_and_compiles() -> None:
    """Cheap guard: the edits sit in the hot loop, so a syntax/name error there would only
    surface when a real daemon started — i.e. in production, silently, as 'no daemon'."""
    proc = subprocess.run(
        [sys.executable, "-c", "import sys; sys.path.insert(0, 'scripts/lib'); sys.path.insert(0, 'scripts'); import daemon"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
