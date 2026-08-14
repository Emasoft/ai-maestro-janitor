"""Real-process integration tests for scripts/daemon.py — the global daemon.

Split out of test_daemon.py (TRDD-ASA7EBJQ, janitor#245): these tests spawn a
REAL long-lived `scripts/daemon.py` process and wait (wall-clock) for it to do
real work. That is fundamentally at odds with the fast parallel unit suite —
under `pytest -n auto` these compete with N-1 other workers for CPU and blow
deadlines tuned on an idle machine, for reasons that have nothing to do with
correctness (measured 2026-08-14: two of these tests FAILED a 30s deadline
under `-n 12` while PASSING in 6s serially).

Every test in this file is `@pytest.mark.integration` and MUST be run as its
own SERIAL CI step (no `-n auto`) — see .github/workflows/ci.yml. The pure
decision layers (`plan_*`, the diagnose/classify functions, stdout parsing,
bulk-lane scheduling) stay in tests/test_daemon.py's fast parallel suite;
only the "spawn a real daemon and observe it" tests live here.

Tests isolate per-tmp_path: JANITOR_GLOBAL_STATE_DIR points at a fresh dir so
the user's real ~/.claude/janitor-global-state/ is never touched. `claude` is
stubbed via a PATH shim (a small Python script) so no real plugin update or
marketplace fetch ever runs; the stub logs each call so tests can assert
exactly which CLI subcommands the daemon invoked.

Cadence intervals are forced to 1 second via env so the daemon fires its
tasks within the test's wait window without us having to mock time.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Optional

import pytest

pytestmark = pytest.mark.integration

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


# Passthrough `taskpolicy`: run the command WITHOUT macOS background QoS.
#
# The bulk lane deliberately launches its detached children under `taskpolicy -b`
# (background QoS: throttled CPU, disk IO and network together) so a ~20 min
# marketplace refresh never starves the user's foreground work. Correct in
# production, ruinous for a test's patience budget — MEASURED on a loaded dev box,
# `uv run scripts/daemon.py --help` costs 1.0 s at normal QoS and 75.5 s under
# `taskpolicy -b`. That is a ~73x swing driven entirely by how busy the machine
# happens to be, so a wait bound sized for the daemon's real work still goes red,
# and it goes red exactly when the machine is busiest: during a publish, which runs
# the full suite. (The recheck-beat knob below was an earlier, partial fix for the
# same red test; it removed ~10 s of poll latency and left the ~150 s of throttled
# boot untouched, which is why the flake survived it.)
#
# Stubbing is not mocking: the REAL code path still runs — the daemon detects
# taskpolicy, builds the ['taskpolicy', '-b'] prefix, and execs it. Only the QoS
# side effect, which no assertion here is about, is neutralized. Same pattern and
# rationale as the `claude` stub above.
#
# Linux is deliberately NOT stubbed. `nice -n 19` + `ionice -c 3` are ordinary
# scheduler hints, not a QoS band, and cost a rounding error next to this; leaving
# them real keeps the Linux prefix genuinely exercised.
#
# Unknown flags are a hard error rather than a silent skip: real taskpolicy has
# value-taking options (-t, -l), and treating one of those as a bare flag would
# exec the VALUE as the command — a stub that quietly runs the wrong process is
# worse than no stub.
_TASKPOLICY_STUB = '''#!/usr/bin/env python3
import os, sys
a = sys.argv[1:]
while a and a[0].startswith("-"):
    if a[0] not in ("-b", "-d", "-g", "-a"):
        sys.stderr.write("taskpolicy stub: unhandled flag %r\\n" % a[0])
        raise SystemExit(64)
    a.pop(0)
if not a:
    raise SystemExit(0)
os.execvp(a[0], a)
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
    # See _TASKPOLICY_STUB: neutralize macOS background QoS so a child boot costs
    # ~1 s instead of ~75 s and this file's waits measure the daemon, not the load.
    (bin_dir / "taskpolicy").write_text(_TASKPOLICY_STUB, encoding="utf-8")
    (bin_dir / "taskpolicy").chmod(0o755)
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
    # Forcing the cadences to 1 s is not enough on its own: the two bulk tasks
    # share ONE serial lane, so the second spawns only after the first child is
    # REAPED — and a reap happens on the _BULK_RECHECK_SEC beat. At the 5 s
    # default that is up to 10 s of pure poll latency inside the 30 s wait,
    # leaving too little headroom for two cold `uv run` child boots on a loaded
    # machine (observed: passing at load ~5, failing at load ~40-74). Shrinking
    # the beat removes the latency the test does not mean to measure; the
    # assertion — that BOTH tasks actually ran — is unchanged.
    base_env["CLAUDE_PLUGIN_OPTION_DAEMON_BULK_RECHECK_INTERVAL"] = "1"

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

    # Teardown: terminate any daemons the test (or its singleton-loser siblings)
    # left alive. Best-effort SIGTERM, then SIGKILL the holdouts.
    #
    # Kill the PROCESS GROUP, not just `proc`. `proc` is the `uv run` LAUNCHER; the
    # daemon is a python CHILD with a different pid — this file's own
    # test_daemon_writes_pid_and_heartbeat documents `written_pid != proc.pid`, and
    # both alive. Signalling only the launcher therefore ORPHANS the daemon, which
    # then runs forever against a state dir pytest has already deleted.
    #
    # Not hypothetical: found one such orphan alive after 2 DAYS (`scripts/daemon.py`
    # under a `janitor-test-session-*` tmp python, its state dir long gone). A test
    # suite that leaves a running daemon behind violates the standing rule that every
    # resource a suite opens is closed before it returns.
    #
    # `start_new_session=True` on the spawn makes each launcher a session leader, so
    # its pgid == its pid and ONE killpg reaches launcher + daemon together. Falling
    # back to the bare proc keeps this correct if getpgid ever fails.
    for proc in spawned:
        if proc.poll() is not None:
            continue
        try:
            pgid: int | None = os.getpgid(proc.pid)
        except OSError:
            pgid = None
        for sig, grace in ((signal.SIGTERM, 3), (signal.SIGKILL, 2)):
            if proc.poll() is not None:
                break
            try:
                if pgid is not None:
                    os.killpg(pgid, sig)
                else:
                    proc.send_signal(sig)
            except OSError:
                break  # already gone
            try:
                proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                pass


# Every deadline in this file is WALL-CLOCK, and these tests spawn a REAL daemon
# process and wait for it to do real work. Those numbers were tuned on an idle
# machine; _DEADLINE_SLACK gives generous ABSOLUTE headroom so a briefly loaded CI
# runner (this file's own serial CI step, or a shared box) does not turn a
# correctness assertion into a load-timing flake.
#
# Because `_wait_for` POLLS, a healthy test still returns the moment its
# condition holds — the headroom costs nothing when things work, and is only
# ever paid when something is genuinely broken.
#
# This is NOT a retry and NOT a sleep: a flaky gate is worse than a slow one,
# because every "verified" claim made against it is weaker than it looks.
_DEADLINE_SLACK = 4.0


def _wait_for(predicate, timeout: float = 8.0, interval: float = 0.1) -> bool:
    """Poll until `predicate()` returns truthy, or timeout. Return its value.

    `timeout` is multiplied by `_DEADLINE_SLACK` (see above) so the same test is
    not held to an idle-machine deadline while a shared runner is briefly busy.
    """
    deadline = time.time() + timeout * _DEADLINE_SLACK
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


def test_daemon_sigterm_records_graceful_exit(harness: dict) -> None:
    """janitor#216: a SIGTERM'd daemon must leave a graceful-exit-history entry
    so the crash-loop breaker can tell an orderly shutdown from a real crash."""
    p = harness["spawn"]()
    pid_path = harness["state_dir"] / "daemon.pid"
    graceful_path = harness["state_dir"] / "daemon.graceful-exit-history"
    assert _wait_for(lambda: pid_path.is_file()), "daemon must start"
    pid = _read_pid(pid_path)
    assert pid is not None

    before = time.time()
    os.kill(pid, signal.SIGTERM)

    assert _wait_for(lambda: not _alive(pid), timeout=15.0), \
        "daemon must exit on SIGTERM"
    assert _wait_for(lambda: graceful_path.is_file(), timeout=5.0), \
        "SIGTERM shutdown must record a graceful-exit-history entry"
    lines = [ln for ln in graceful_path.read_text(encoding="utf-8").splitlines() if ln.strip().isdigit()]
    assert lines, "graceful-exit-history must carry at least one epoch"
    assert int(lines[-1]) >= int(before) - 1, "the recorded epoch must be around the SIGTERM time"
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
# regex and the global_state helpers (tests/test_daemon.py, tests/test_global_state.py).


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
