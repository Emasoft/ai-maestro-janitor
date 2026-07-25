"""Tests for scripts/daemon.py — the global single-instance daemon.

The daemon is exercised as a subprocess (the real invocation surface). Tests
isolate per-tmp_path: JANITOR_GLOBAL_STATE_DIR points at a fresh dir so the
user's real ~/.claude/janitor-global-state/ is never touched. `claude` is
stubbed via a PATH shim (a small Python script) so no real plugin update
or marketplace fetch ever runs; the stub logs each call so tests can assert
exactly which CLI subcommands the daemon invoked.

Cadence intervals are forced to 1 second via env so the daemon fires its
tasks within the test's wait window without us having to mock time.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DAEMON = _PROJECT_ROOT / "scripts" / "daemon.py"

assert _DAEMON.is_file(), f"daemon not found at {_DAEMON}"


# Stub `claude`: dispatches on argv, logs every invocation, returns canned
# responses for the three subcommands the daemon uses. Setting CLAUDE_STUB_FORCE_UPDATE=1
# makes every `plugin update` emit the "Updated from vX to vY" marker so the
# daemon's stdout-parser routes to set_reload_flag.
_CLAUDE_STUB = '''#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
log = os.environ.get("CLAUDE_STUB_LOG", "")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(" ".join(a) + "\\n")
if a[:3] == ["plugin", "marketplace", "update"]:
    sys.stdout.write("Updated 1 marketplace.\\n")
    raise SystemExit(0)
if a[:3] == ["plugin", "list", "--json"]:
    payload = [
        {"id": "test-plugin-a@mp", "scope": "user", "enabled": True},
        {"id": "test-plugin-b@mp", "scope": "user", "enabled": False},
        {"id": "test-plugin-c@mp", "scope": "local", "enabled": True},
    ]
    sys.stdout.write(json.dumps(payload))
    raise SystemExit(0)
if a[:2] == ["plugin", "update"]:
    if os.environ.get("CLAUDE_STUB_FORCE_UPDATE") == "1":
        sys.stdout.write("Updated from v0.4.13 to v0.5.0\\n")
    raise SystemExit(0)
sys.stderr.write("claude-stub: unhandled %r\\n" % (a,))
raise SystemExit(99)
'''


@pytest.fixture
def harness(tmp_path: Path):
    """Set up the daemon's isolated runtime: state dir + stub claude on PATH.

    Yields a dict with paths the test needs. Tears down any spawned daemon
    by SIGKILL'ing PIDs it produced so a flaky assertion can never leave a
    real daemon process behind.
    """
    state_dir = tmp_path / "state"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "claude").write_text(_CLAUDE_STUB, encoding="utf-8")
    (bin_dir / "claude").chmod(0o755)
    stub_log = tmp_path / "claude.log"

    base_env = os.environ.copy()
    base_env["JANITOR_GLOBAL_STATE_DIR"] = str(state_dir)
    # The six mode flags (incl. reload-needed.flag) now live at the FIXED control_dir()
    # (ARCHITECTURE.md §7.1, TRDD-QK7M2B0X), not global_state_dir() — pin it to the SAME
    # isolated state_dir so this file's raw `harness["state_dir"] / "<flag>"` assertions
    # still find what the daemon's set_reload_flag() writes, and so no daemon test here
    # shares the real process's ~/.claude/janitor-control.
    base_env["JANITOR_CONTROL_DIR"] = str(state_dir)
    base_env["PATH"] = f"{bin_dir}{os.pathsep}{base_env['PATH']}"
    base_env["CLAUDE_STUB_LOG"] = str(stub_log)
    # Isolate the OAuth-rotator root so the 60 s oauth-rotator-tick Task resolves
    # to an empty tmp dir (no opt-in.flag → a total no-op) and can NEVER touch the
    # user's real keychain / slots during a daemon test. Without this the daemon
    # would inherit whatever CLAUDE_PLUGIN_DATA happens to be in os.environ.
    base_env["CLAUDE_PLUGIN_DATA"] = str(tmp_path / "plugin-data")
    # Belt-and-suspenders for the OS keepalive: the daemon already refuses to
    # auto-install one unless it runs from the plugin cache (a daemon spawned from
    # this dev-checkout path never does), but pin the opt-out explicitly so no test
    # can ever register a real ~/Library/LaunchAgents plist on the dev machine.
    base_env["CLAUDE_PLUGIN_OPTION_DAEMON_OS_KEEPALIVE"] = "0"
    # Pin the CHORE-OWNERSHIP signal. `server_runs_chores()` resolves
    # $JANITOR_AIMAESTRO_SERVER_CHORES -> $JANITOR_AIMAESTRO_SERVER_STATE -> a LIVE
    # probe of ~/.aimaestro/server-liveness.json. Unpinned, these tests read that REAL
    # machine-wide file: if an ai-maestro server happens to be running on the dev box
    # (or in CI), the daemon CORRECTLY yields every SERVER_ABSORBED_TASK — which
    # includes both marketplace-refresh and user-plugins-update — and the assertions
    # below fail on a daemon that did exactly the right thing. Observed for real: the
    # suite passed, a server came up, and the same commit then failed the publish gate.
    # "0" = the server does NOT own the chores, so the daemon runs them deterministically.
    base_env["JANITOR_AIMAESTRO_SERVER_CHORES"] = "0"
    # Fire tasks every second during tests so the assertion window is short.
    base_env["CLAUDE_PLUGIN_OPTION_DAEMON_MARKETPLACE_REFRESH_INTERVAL"] = "1"
    base_env["CLAUDE_PLUGIN_OPTION_DAEMON_USER_PLUGINS_UPDATE_INTERVAL"] = "1"

    spawned: list[subprocess.Popen[bytes]] = []

    def spawn(*extra_args: str) -> subprocess.Popen[bytes]:
        # Invoke via the shebang (`uv run --script --quiet`); uv is on PATH on
        # any host running these tests (uvx is what's running pytest itself).
        # extra_args lets a test pass daemon flags (e.g. "--keepalive") — they go
        # AFTER the script so the daemon's `"--keepalive" in sys.argv` sees them.
        proc = subprocess.Popen(
            [str(_DAEMON), *extra_args],
            env=base_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        spawned.append(proc)
        return proc

    yield {
        "state_dir": state_dir,
        "bin_dir": bin_dir,
        "stub_log": stub_log,
        "env": base_env,
        "spawn": spawn,
    }

    # Teardown: terminate any daemons the test (or its singleton-loser
    # siblings) left alive. Best-effort, then SIGKILL the holdouts.
    for proc in spawned:
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass


def _wait_for(predicate, timeout: float = 8.0, interval: float = 0.1) -> bool:
    """Poll until `predicate()` returns truthy, or timeout. Return its value."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        v = predicate()
        if v:
            return v
        time.sleep(interval)
    return predicate()


def _read_pid(pid_path: Path) -> Optional[int]:
    if not pid_path.is_file():
        return None
    try:
        return int(pid_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def test_daemon_writes_pid_and_heartbeat(harness: dict) -> None:
    """Daemon writes its pid file and heartbeat ts shortly after startup."""
    harness["spawn"]()  # fixture keeps the Popen ref alive for teardown
    pid_path = harness["state_dir"] / "daemon.pid"
    hb_path = harness["state_dir"] / "daemon.heartbeat.ts"

    assert _wait_for(lambda: pid_path.is_file() and hb_path.is_file()), \
        "pid + heartbeat files must appear within 8 s"
    written_pid = _read_pid(pid_path)
    assert written_pid is not None
    assert _alive(written_pid), "the PID in daemon.pid must be a live process"
    # The pid written by the daemon is its OWN process; with the `uv run`
    # shebang the daemon is a python child of the uv launcher (proc.pid),
    # so written_pid ≠ proc.pid in general but both are alive.


def test_keepalive_daemon_records_a_spawn_attempt(harness: dict) -> None:
    """KEEPQRTN HIGH-2: a daemon launched on the OS-keepalive path (--keepalive) records a
    spawn-attempt stamp in daemon.spawn-history at startup, so a die-on-start OS-respawn loop
    becomes visible to crash_loop_active() and C4 can quarantine the bad version. Without
    this the OS path wrote NOTHING and the breaker never tripped (the rollback gap)."""
    harness["spawn"]("--keepalive")
    hist = harness["state_dir"] / "daemon.spawn-history"
    assert _wait_for(lambda: hist.is_file() and hist.read_text(encoding="utf-8").strip()), \
        "the --keepalive daemon must record a spawn attempt within 8 s"
    lines = [ln for ln in hist.read_text(encoding="utf-8").splitlines() if ln.strip().isdigit()]
    assert len(lines) == 1, f"exactly one spawn-attempt stamp expected, got {lines}"


def test_session_daemon_does_not_double_record_in_main(harness: dict) -> None:
    """KEEPQRTN HIGH-2 (the don't-double-count half): a daemon whose main() runs WITHOUT
    --keepalive (the session path) records NOTHING in main() — the session path's stamp is
    written by spawn_daemon_detached, not main(). Recording in BOTH would double-count and
    falsely trip the breaker on the normal session path. Proven by: main() comes up (pid +
    heartbeat appear) yet leaves daemon.spawn-history absent/empty."""
    harness["spawn"]()  # no --keepalive → the session-style invocation of main()
    pid_path = harness["state_dir"] / "daemon.pid"
    hb_path = harness["state_dir"] / "daemon.heartbeat.ts"
    assert _wait_for(lambda: pid_path.is_file() and hb_path.is_file()), \
        "the session daemon must come up (pid + heartbeat) within 8 s"
    # main() is well past the spawn-attempt record point now (pid + heartbeat are written
    # AFTER it). It must NOT have written a spawn-history entry from main() itself.
    hist = harness["state_dir"] / "daemon.spawn-history"
    lines = (
        [ln for ln in hist.read_text(encoding="utf-8").splitlines() if ln.strip().isdigit()]
        if hist.is_file()
        else []
    )
    assert lines == [], f"main() must not record a spawn attempt off the keepalive path, got {lines}"


def test_daemon_runs_marketplace_refresh_and_user_plugins_update(harness: dict) -> None:
    """Within the first cadence window the daemon invokes both tasks' CLI calls."""
    harness["spawn"]()
    stub_log = harness["stub_log"]

    # Wait for the stub log to contain BOTH marketplace update and at least
    # one user-scope plugin update (proves user-plugins-update enumerated
    # and filtered the list, then dispatched the per-plugin update).
    def saw_both() -> bool:
        if not stub_log.is_file():
            return False
        lines = stub_log.read_text(encoding="utf-8").splitlines()
        return any("plugin marketplace update" in ln for ln in lines) and \
               any("plugin update test-plugin-a@mp --scope user" in ln for ln in lines)

    # 30 s: bulk tasks run via the background lane (one at a time) since the
    # 2026-07-17 starvation fix, so user-plugins-update spawns only after the
    # marketplace-refresh child is REAPED — up to two _BULK_RECHECK_SEC beats
    # plus both child runtimes.
    assert _wait_for(saw_both, timeout=30.0), "daemon must run both tasks"

    # Sanity: the local-scope plugin in the stub list must NOT have been
    # updated by the daemon (user-scope is the daemon's job, not local-scope).
    lines = stub_log.read_text(encoding="utf-8").splitlines()
    assert not any("plugin update test-plugin-c@mp" in ln for ln in lines), \
        "local-scope plugin must be filtered out by the daemon"


def test_daemon_singleton_second_spawn_exits(harness: dict) -> None:
    """Two parallel spawns → only one acquires the flock; the second exits."""
    p1 = harness["spawn"]()
    pid_path = harness["state_dir"] / "daemon.pid"
    assert _wait_for(lambda: pid_path.is_file()), "first daemon must write pid"
    first_pid = _read_pid(pid_path)
    assert first_pid is not None

    # Second spawn — must exit silently because flock is held by the first.
    p2 = harness["spawn"]()
    # p2 is the `uv run` launcher PID; we wait for the whole process tree to
    # exit by polling its returncode.
    assert _wait_for(lambda: p2.poll() is not None, timeout=10.0), \
        "second daemon must exit because the flock is held"

    # The pid file must STILL reference the first daemon (not overwritten).
    assert _read_pid(pid_path) == first_pid

    # And the first daemon must still be alive.
    assert _alive(first_pid)
    _ = p1  # keep ref for teardown


def test_daemon_kill_switch_exits(harness: dict) -> None:
    """Touching kill-switch.flag makes the running daemon exit gracefully."""
    p = harness["spawn"]()
    pid_path = harness["state_dir"] / "daemon.pid"
    assert _wait_for(lambda: pid_path.is_file()), "daemon must start"
    pid = _read_pid(pid_path)
    assert pid is not None

    # Trip the kill switch.
    (harness["state_dir"] / "kill-switch.flag").touch()

    # Daemon should exit within one loop ceiling (~60 s); the daemon ticks
    # in 1-second increments so this is generally < 3 s in practice.
    assert _wait_for(lambda: not _alive(pid), timeout=15.0), \
        "daemon must observe kill-switch and exit"
    # PID file should be cleaned up.
    assert _wait_for(lambda: not pid_path.is_file(), timeout=5.0), \
        "graceful shutdown must remove daemon.pid"
    _ = p


def test_daemon_sigterm_graceful_shutdown(harness: dict) -> None:
    """SIGTERM to the daemon triggers graceful exit + cleanup."""
    p = harness["spawn"]()
    pid_path = harness["state_dir"] / "daemon.pid"
    assert _wait_for(lambda: pid_path.is_file()), "daemon must start"
    pid = _read_pid(pid_path)
    assert pid is not None

    # SIGTERM the daemon process directly.
    os.kill(pid, signal.SIGTERM)

    assert _wait_for(lambda: not _alive(pid), timeout=15.0), \
        "daemon must exit on SIGTERM"
    assert _wait_for(lambda: not pid_path.is_file(), timeout=5.0), \
        "graceful shutdown removes the pid file"
    _ = p


def test_daemon_marks_last_run_after_task(harness: dict) -> None:
    """Each task records its last-run.ts on completion."""
    _ = harness["spawn"]()
    mr_path = harness["state_dir"] / "marketplace-refresh.last-run.ts"
    up_path = harness["state_dir"] / "user-plugins-update.last-run.ts"

    # 30 s: since the background-lane fix a bulk task's stamp lands at child REAP
    # time (serialized lane), not synchronously — see the saw_both timeout note.
    assert _wait_for(lambda: mr_path.is_file() and up_path.is_file(), timeout=30.0), \
        "both task last-run files must be written"
    # Stamps must be sensible epoch seconds (within the last minute).
    now = int(time.time())
    for p in (mr_path, up_path):
        ts = int(p.read_text(encoding="utf-8").strip())
        assert abs(now - ts) < 60, f"stamp {ts} unreasonably far from now {now}"


# ---------- reload-flag integration tests ----------------------------------
#
# These exercise the daemon's stdout-parser + set_reload_flag wiring end-to-end
# through the subprocess interface, complementing the unit tests for the
# regex below and the global_state helpers in test_global_state.py.


def test_daemon_writes_reload_flag_when_plugin_updated(harness: dict) -> None:
    """When `claude plugin update` stdout shows an "Updated from ... to ..." line,
    the daemon must set reload-needed.flag for dispatch to surface."""
    harness["env"]["CLAUDE_STUB_FORCE_UPDATE"] = "1"
    harness["spawn"]()
    flag = harness["state_dir"] / "reload-needed.flag"
    # 30 s: the flag is set by the user-plugins-update background child, which
    # spawns only after marketplace-refresh clears the bulk lane.
    assert _wait_for(lambda: flag.is_file(), timeout=30.0), \
        "reload-needed.flag must be written after a real plugin update"
    body = flag.read_text(encoding="utf-8")
    assert "test-plugin-a@mp" in body, \
        f"flag body must record the updated plugin id, got {body!r}"


def test_daemon_does_not_write_reload_flag_when_nothing_updated(harness: dict) -> None:
    """A clean `plugin update` (no "Updated" marker in stdout) → no flag.

    The stub returns rc=0 with empty stdout by default, simulating "already
    up to date". The daemon must NOT set the reload flag in that case —
    spurious [janitor-reload] markers would force /reload-plugins on every
    no-op cadence.
    """
    # Note: CLAUDE_STUB_FORCE_UPDATE is NOT set here (default behavior).
    harness["spawn"]()
    # Wait until at least one user-plugins-update completes so the daemon
    # has had its chance to set the flag.
    up_path = harness["state_dir"] / "user-plugins-update.last-run.ts"
    # 30 s: stamp-at-reap through the serialized bulk lane (see saw_both note).
    assert _wait_for(lambda: up_path.is_file(), timeout=30.0)
    # Now the flag must NOT exist.
    flag = harness["state_dir"] / "reload-needed.flag"
    assert not flag.is_file(), "reload flag must not be set when no plugin actually updated"


# ---------- in-process unit test for the stdout parser ---------------------

sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))


def _import_daemon_module():
    """Import scripts/daemon.py as a module so we can call its helpers directly.

    The shebang line + PEP 723 block is harmless inside Python's import path;
    only the `if __name__ == '__main__'` guard prevents main() from running.
    """
    import importlib.util as _u
    spec = _u.spec_from_file_location("janitor_daemon_under_test", str(_DAEMON))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("stdout,expected", [
    ("Updated from v0.4.13 to v0.5.0\n",                                True),
    ("Updated to v0.5.0\n",                                             True),
    ("v0.4.13 -> v0.5.0\n",                                             True),
    ("v0.4.13 → v0.5.0\n",                                              True),
    ("Installed version 0.5.0\n",                                       True),
    ("Already up to date.\n",                                           False),
    ("already up-to-date\n",                                            False),
    ("",                                                                False),
    # Real update line co-existing with an "already up to date" line is still
    # a real update — the parser walks lines and ignores no-change ones.
    ("Updated to v1.0.0\nAlready up to date.\n",                        True),
    # The plain word "updated" without the from/to structural keywords is NOT
    # treated as a version transition — false positives are worse than misses.
    ("nothing was updated\n",                                           False),
])
def test_stdout_parser_classifies_correctly(stdout: str, expected: bool) -> None:
    """The stdout parser must distinguish real version changes from no-ops."""
    daemon = _import_daemon_module()
    assert daemon._stdout_proves_plugin_updated(stdout) is expected


# ---------- rules-cleanup task (TRDD-H9IBY95W) -----------------------------
#
# Post-uninstall orphaned-rule cleanup. Registered at 1 h; delegates to
# rules_installer.cleanup_user_orphans_if_uninstalled (which no-ops unless the
# janitor is fully uninstalled). Opt-out via CLAUDE_PLUGIN_OPTION_RULES_CLEANUP_ENABLED.


def test_rules_cleanup_registered_at_1h() -> None:
    daemon = _import_daemon_module()
    tasks = {t.name: t for t in daemon._build_tasks()}
    assert "rules-cleanup" in tasks
    assert tasks["rules-cleanup"].interval_s == 3600


def test_rules_cleanup_noop_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """The opt-out env var short-circuits before the installer is ever consulted."""
    daemon = _import_daemon_module()
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_RULES_CLEANUP_ENABLED", "0")
    called = {"n": 0}
    monkeypatch.setattr(
        daemon.ri, "cleanup_user_orphans_if_uninstalled",
        lambda: (called.__setitem__("n", called["n"] + 1) or []),
    )
    daemon.task_rules_cleanup()
    assert called["n"] == 0, "disabled → the installer cleanup is never called"


def test_rules_cleanup_delegates_to_installer_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enabled (default) → the task calls the installer's uninstall-gated cleanup."""
    daemon = _import_daemon_module()
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_RULES_CLEANUP_ENABLED", raising=False)
    called = {"n": 0}
    monkeypatch.setattr(
        daemon.ri, "cleanup_user_orphans_if_uninstalled",
        lambda: (called.__setitem__("n", called["n"] + 1) or ["/home/x/.claude/rules/commit-discipline.md"]),
    )
    monkeypatch.setattr(daemon.state, "log_line", lambda *_a, **_k: None)
    daemon.task_rules_cleanup()
    assert called["n"] == 1, "enabled → delegates to the installer cleanup exactly once"


# ---------- oauth-rotator-tick task (TRDD-f892e109 decision 3) --------------
#
# The daemon's 60 s oauth-rotator-tick Task REPLACED the launchd agent. These
# in-process unit tests prove it is registered, no-ops when not opted in, and
# otherwise runs rotator.py as a TIMED subprocess (so a hung keychain/usage
# call can't wedge the loop).


def test_oauth_rotator_tick_registered_at_60s() -> None:
    """_build_tasks() includes the oauth-rotator-tick Task at the 60 s cadence."""
    daemon = _import_daemon_module()
    tasks = {t.name: t for t in daemon._build_tasks()}
    assert "oauth-rotator-tick" in tasks
    assert tasks["oauth-rotator-tick"].interval_s == 60


def test_oauth_rotator_tick_noop_when_not_opted_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """No opt-in flag → the tick task never spawns the rotator subprocess."""
    daemon = _import_daemon_module()
    calls: list[list[str]] = []
    monkeypatch.setattr(daemon.oauth_supervisor, "opt_in_present", lambda *_a, **_k: False)
    monkeypatch.setattr(daemon, "_run_workload", lambda cmd, **_k: calls.append(cmd))
    daemon.task_oauth_rotator_tick()
    assert calls == [], "tick must be a total no-op when not opted in"


def test_oauth_rotator_tick_runs_rotator_when_opted_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Opt-in flag present → the tick runs `rotator.py tick --only-if-claude-running`
    via _run_workload (a TIMED subprocess, never in-process)."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))  # isolate the flock
    daemon = _import_daemon_module()
    calls: list[list[str]] = []
    monkeypatch.setattr(daemon.oauth_supervisor, "opt_in_present", lambda *_a, **_k: True)
    monkeypatch.setattr(daemon, "_run_workload", lambda cmd, **_k: calls.append(cmd))
    daemon.task_oauth_rotator_tick()
    assert len(calls) == 1
    cmd = calls[0]
    assert cmd[1].endswith("rotator.py")
    assert cmd[-2:] == ["tick", "--only-if-claude-running"]


def test_oauth_rotator_tick_does_not_gate_on_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SINGLE-WRITER lives in the SUBPROCESS, not the daemon wrapper (P3, audit §3.4):
    even when the rotator-tick flock is HELD, the daemon STILL spawns `rotator.py tick`
    — the rotator's own main() self-locks and skips internally. A daemon-side lock would
    instead block the daemon's OWN subprocess from ever acquiring the flock (and would
    never see a human's manual `rotator.py` run), so the daemon must NOT gate on it."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))
    daemon = _import_daemon_module()
    calls: list[list[str]] = []
    monkeypatch.setattr(daemon.oauth_supervisor, "opt_in_present", lambda *_a, **_k: True)
    monkeypatch.setattr(daemon, "_run_workload", lambda cmd, **_k: calls.append(cmd))
    # Hold the real flock — the daemon must STILL spawn the subprocess (which self-locks).
    held = daemon.gs.acquire_oauth_rotator_lock()
    assert held is not None
    try:
        daemon.task_oauth_rotator_tick()
        assert len(calls) == 1, "daemon must spawn rotator.py regardless of the lock"
        assert calls[0][-2:] == ["tick", "--only-if-claude-running"]
    finally:
        daemon.gs.release_oauth_rotator_lock(held)


# ---------- _run_workload kill-path reap (audit finding 4) -----------------
#
# On timeout/shutdown _run_workload kills the child then drains it with
# communicate() (not wait()), so the PIPE stdout/stderr fds close deterministically
# instead of waiting on GC. These tests run a REAL sleeping subprocess (no mocks)
# and assert the call is bounded, returns None, and the child is reaped.


def _isolate_project_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, daemon) -> None:
    """Pin `state.log_line`'s target to tmp AND flush the process-lifetime lru caches.

    WHY (2026-07-17 flake root-cause): `state.project_root` & friends memoise the
    FIRST resolution for the whole pytest process. Without this, the kill-path tests
    (a) write real log lines into the REPO's `.janitor/`, (b) spawn a
    `git rev-parse` fallback INSIDE a patched-Popen window (breaking the
    exactly-one-child assertion), and (c) pin the repo root so every LATER test's
    monkeypatched CLAUDE_PROJECT_DIR is silently ignored — which made the
    chore-coordination watchdog test dedupe against the REAL repo's seen-file."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "proj"))
    (tmp_path / "proj").mkdir(exist_ok=True)
    for fn in (daemon.state.project_root, daemon.state.janitor_root,
               daemon.state.state_dir, daemon.state.log_dir):
        fn.cache_clear()


def test_run_workload_kills_hung_child_and_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A child that sleeps past the timeout is killed; _run_workload returns None fast."""
    daemon = _import_daemon_module()
    # Isolate global state so write_heartbeat() during the tick lands in tmp.
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gstate"))
    _isolate_project_paths(tmp_path, monkeypatch, daemon)
    daemon.gs.init_global_state()

    start = time.time()
    result = daemon._run_workload(["sleep", "30"], timeout=1, heartbeat_tick=1)
    elapsed = time.time() - start

    assert result is None, "a killed/timed-out workload must return None"
    assert elapsed < 10.0, f"kill path wedged for {elapsed:.1f}s — timeout did not fire"


def test_run_workload_kill_path_closes_pipe_fds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After the kill-path reap, the child's PIPE fds are closed deterministically.

    communicate() (the fix) drains and closes proc.stdout/proc.stderr; the old
    wait() left them open until GC. We capture the Popen object the function
    creates (by wrapping Popen) and assert its pipe file objects are closed once
    _run_workload returns — proof the reap closed them here, not via GC.
    """
    daemon = _import_daemon_module()
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gstate"))
    # MUST precede the Popen patch: an unpinned project root makes log_line's
    # `git rev-parse` fallback a SECOND captured Popen (see _isolate_project_paths).
    _isolate_project_paths(tmp_path, monkeypatch, daemon)
    daemon.gs.init_global_state()

    captured: list = []
    real_popen = daemon.subprocess.Popen

    def _capturing_popen(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        captured.append(proc)
        return proc

    monkeypatch.setattr(daemon.subprocess, "Popen", _capturing_popen)

    result = daemon._run_workload(["sleep", "30"], timeout=1, heartbeat_tick=1)
    assert result is None
    assert len(captured) == 1, "exactly one child should have been spawned"
    proc = captured[0]
    # communicate() sets the pipe attrs to closed file objects; verify closed.
    assert proc.stdout is None or proc.stdout.closed, "stdout pipe fd must be closed"
    assert proc.stderr is None or proc.stderr.closed, "stderr pipe fd must be closed"
    assert proc.poll() is not None, "the child must be reaped (not a zombie/alive)"


def test_run_workload_normal_completion_returns_completedprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fast child that exits under the timeout returns a CompletedProcess with output."""
    daemon = _import_daemon_module()
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gstate"))
    daemon.gs.init_global_state()

    result = daemon._run_workload(
        [sys.executable, "-c", "print('ok')"], timeout=10, heartbeat_tick=5
    )
    assert result is not None, "a normally-completing workload must return CompletedProcess"
    assert result.returncode == 0
    assert "ok" in result.stdout


def test_user_plugins_update_excludes_ai_maestro_fleet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R2 (TRDD-db169d9e): the per-plugin update SKIPS ai-maestro-plugins members
    (incl. the janitor itself — its self-update is task_version_update) and still
    updates foreign user-scope plugins."""
    import state  # first-party — sys.path for scripts/lib is set up below the top imports

    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))
    monkeypatch.setenv("JANITOR_PLUGINS_ROOT", str(tmp_path / "noplugins"))  # empty → hardcoded fleet
    state.ai_maestro_marketplace_members.cache_clear()

    daemon = _import_daemon_module()
    listing = json.dumps([
        {"id": "ai-maestro-maintainer-agent@ai-maestro-plugins", "scope": "user"},
        {"id": "ai-maestro-janitor@ai-maestro-plugins", "scope": "user"},
        {"id": "community-helper@some-market", "scope": "user"},
        {"id": "proj-only@mp", "scope": "project"},
    ])
    updates: list[str] = []

    def fake_run_workload(cmd, **_kw):
        if cmd[:3] == ["claude", "plugin", "list"]:
            return subprocess.CompletedProcess(cmd, 0, listing, "")
        if cmd[:3] == ["claude", "plugin", "update"]:
            updates.append(cmd[3])
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(daemon, "_run_workload", fake_run_workload)
    monkeypatch.setattr(daemon, "_running", True)

    daemon.task_user_plugins_update()

    assert "community-helper@some-market" in updates          # foreign user plugin → updated
    assert "ai-maestro-maintainer-agent@ai-maestro-plugins" not in updates  # fleet → excluded
    assert "ai-maestro-janitor@ai-maestro-plugins" not in updates           # self-update path is separate
    assert "proj-only@mp" not in updates                      # not user-scope anyway


# ---------- Pillar 1: per-task supervision + subprocess retry (TRDD-7100178d) ----
#
# Task.run() must NEVER let a crashing task kill the daemon (already true) AND must
# quarantine a permanently-broken task with exponential backoff so it stops burning
# its cadence every tick. _run_workload retries a NON-ZERO exit exactly once.


def _daemon_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Import the daemon with its global state pinned to a throwaway dir (so Task
    failcount/last-run files land in tmp, never the user's real state dir)."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))
    daemon = _import_daemon_module()
    daemon.gs.init_global_state()
    return daemon


def test_task_success_keeps_zero_failcount(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A task whose fn succeeds records no failure streak and stays on its bare cadence."""
    daemon = _daemon_isolated(tmp_path, monkeypatch)
    t = daemon.Task("ok-task", 1000, lambda: None)
    t.run()
    assert t._failcount() == 0
    assert t._backoff_penalty(t._failcount()) == 0


def test_task_failure_increments_streak_without_killing_daemon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A task that raises is caught (daemon survives) and its consecutive-failure streak grows."""
    daemon = _daemon_isolated(tmp_path, monkeypatch)

    def boom() -> None:
        raise RuntimeError("kaboom")

    t = daemon.Task("bad-task", 1000, boom)
    t.run()
    t.run()
    t.run()  # three crashes in a row — none may propagate
    assert t._failcount() == 3


def test_task_backoff_penalty_math(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Quarantine backoff is 0 below K, then interval * 2**(fails-K), capped at the ceiling."""
    daemon = _daemon_isolated(tmp_path, monkeypatch)
    t = daemon.Task("bo", 60, lambda: None)
    assert t._backoff_penalty(2) == 0                                  # below K (=3)
    assert t._backoff_penalty(3) == 60                                 # interval * 2**0
    assert t._backoff_penalty(4) == 120                                # interval * 2**1
    assert t._backoff_penalty(5) == 240                                # interval * 2**2
    assert t._backoff_penalty(999) == daemon._TASK_MAX_BACKOFF_SEC     # capped


def test_task_quarantine_defers_next_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """After K consecutive failures, time_until_due() adds the backoff penalty (quarantine)."""
    daemon = _daemon_isolated(tmp_path, monkeypatch)

    def boom() -> None:
        raise RuntimeError("x")

    t = daemon.Task("q", 1000, boom)
    for _ in range(daemon._TASK_BACKOFF_AFTER_FAILS):   # reach K → penalty == interval (1000)
        t.run()
    due = t.time_until_due()                            # last_run ≈ now, so due ≈ interval + penalty
    assert due > 1000, "a quarantined task must wait longer than its bare cadence"
    assert due >= 1990, "the backoff penalty (=interval at K) must be added to the cadence"


def test_task_success_resets_streak(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A single success clears an accumulated failure streak → back to the normal cadence."""
    daemon = _daemon_isolated(tmp_path, monkeypatch)
    box = {"fail": True}

    def maybe() -> None:
        if box["fail"]:
            raise RuntimeError("x")

    t = daemon.Task("r", 1000, maybe)
    t.run()
    t.run()
    assert t._failcount() == 2
    box["fail"] = False
    t.run()
    assert t._failcount() == 0
    assert t._backoff_penalty(t._failcount()) == 0


def test_run_workload_retries_once_on_nonzero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A workload exiting NON-ZERO is retried exactly once (two real child spawns)."""
    daemon = _daemon_isolated(tmp_path, monkeypatch)
    captured: list = []
    real_popen = daemon.subprocess.Popen

    def cap(*a, **k):
        proc = real_popen(*a, **k)
        captured.append(proc)
        return proc

    monkeypatch.setattr(daemon.subprocess, "Popen", cap)
    result = daemon._run_workload([sys.executable, "-c", "import sys; sys.exit(3)"], timeout=10)
    assert result is not None and result.returncode == 3
    assert len(captured) == 2, "a non-zero exit must be retried exactly once"


def test_run_workload_no_retry_on_clean_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clean rc==0 workload is NOT retried (a single child spawn)."""
    daemon = _daemon_isolated(tmp_path, monkeypatch)
    captured: list = []
    real_popen = daemon.subprocess.Popen

    def cap(*a, **k):
        proc = real_popen(*a, **k)
        captured.append(proc)
        return proc

    monkeypatch.setattr(daemon.subprocess, "Popen", cap)
    result = daemon._run_workload([sys.executable, "-c", "pass"], timeout=10)
    assert result is not None and result.returncode == 0
    assert len(captured) == 1, "a clean exit must not be retried"
