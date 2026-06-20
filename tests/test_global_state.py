"""Tests for scripts/lib/global_state.py — the daemon's shared contract.

These tests exercise the building blocks in-process: directory resolution
respecting `$JANITOR_GLOBAL_STATE_DIR`, exclusive flock semantics, and the
daemon-liveness truth table (no pid / dead pid / stale heartbeat / live +
fresh). Subprocess-level daemon tests live in test_daemon.py.

Per-test isolation: the helper builds a fresh tmp state dir per test, points
JANITOR_GLOBAL_STATE_DIR at it, and reloads global_state to drop any
cached state. Tests use the running pytest PID as a guaranteed-alive PID.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))


@pytest.fixture
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated global state dir per test (no shared ~/.claude/ pollution)."""
    d = tmp_path / "janitor-global-state"
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(d))
    # Force a clean import so the lru-cache / module-state from a previous
    # test cannot leak — global_state itself reads env at call time so this
    # is mostly defensive.
    for mod in ("global_state",):
        if mod in sys.modules:
            del sys.modules[mod]
    return d


def _gs():
    """Import the module fresh after the env is set."""
    import global_state  # type: ignore[import-not-found]
    return global_state


def test_global_state_dir_respects_env_override(state_dir: Path) -> None:
    """$JANITOR_GLOBAL_STATE_DIR overrides the default ~/.claude/... location."""
    assert _gs().global_state_dir() == state_dir.resolve()


def test_init_global_state_creates_dir(state_dir: Path) -> None:
    """init_global_state() is idempotent — calling it twice is safe."""
    _gs().init_global_state()
    _gs().init_global_state()
    assert state_dir.is_dir()


def test_singleton_flock_first_acquires_second_fails(state_dir: Path) -> None:
    """One process holding the flock blocks every other acquire attempt."""
    gs = _gs()
    fd1 = gs.acquire_singleton_flock()
    assert fd1 is not None, "first acquire must succeed"
    try:
        fd2 = gs.acquire_singleton_flock()
        assert fd2 is None, "second acquire must be denied while fd1 holds the lock"
    finally:
        gs.release_singleton_flock(fd1)


def test_singleton_flock_released_lets_next_acquire(state_dir: Path) -> None:
    """Releasing the flock lets a subsequent acquire succeed (no stale state)."""
    gs = _gs()
    fd1 = gs.acquire_singleton_flock()
    assert fd1 is not None
    gs.release_singleton_flock(fd1)
    fd2 = gs.acquire_singleton_flock()
    assert fd2 is not None
    gs.release_singleton_flock(fd2)


def test_daemon_is_alive_no_pid_file(state_dir: Path) -> None:
    """A missing pid file means definitely-not-alive."""
    gs = _gs()
    gs.init_global_state()
    assert gs.daemon_is_alive() is False


def test_daemon_is_alive_dead_pid(state_dir: Path) -> None:
    """A pid file referencing a non-existent PID means not-alive."""
    gs = _gs()
    gs.init_global_state()
    gs.write_daemon_pid(999_999)  # vanishingly unlikely to be a real PID
    gs.write_heartbeat()  # fresh heartbeat is irrelevant when PID is dead
    assert gs.daemon_is_alive() is False


def test_daemon_is_alive_stale_heartbeat(state_dir: Path) -> None:
    """A live PID with a stale heartbeat counts as not-alive (stuck daemon)."""
    gs = _gs()
    gs.init_global_state()
    gs.write_daemon_pid(os.getpid())  # the pytest process itself — surely alive
    gs.write_heartbeat(now=int(time.time()) - (gs.DEFAULT_DAEMON_STALE_SECONDS + 60))
    assert gs.daemon_is_alive() is False


def test_daemon_is_alive_fresh_heartbeat(state_dir: Path) -> None:
    """Live PID + recent heartbeat → alive."""
    gs = _gs()
    gs.init_global_state()
    gs.write_daemon_pid(os.getpid())
    gs.write_heartbeat()
    assert gs.daemon_is_alive() is True


def test_kill_switch_present_detects_flag(state_dir: Path) -> None:
    """Touching kill-switch.flag is the documented disable signal."""
    gs = _gs()
    gs.init_global_state()
    assert gs.kill_switch_present() is False
    (state_dir / "kill-switch.flag").touch()
    assert gs.kill_switch_present() is True


def test_ensure_daemon_running_respects_kill_switch(state_dir: Path) -> None:
    """When kill-switch is set, ensure_daemon_running() never spawns."""
    gs = _gs()
    gs.init_global_state()
    (state_dir / "kill-switch.flag").touch()
    # Should return False (not alive, not spawned).
    assert gs.ensure_daemon_running() is False
    # No PID file should have been created.
    assert not (state_dir / "daemon.pid").exists()


def test_ensure_daemon_running_respects_master_disable(
    state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """daemon_enabled=false silences ensure_daemon_running() entirely."""
    gs = _gs()
    gs.init_global_state()
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_DAEMON_ENABLED", "false")
    assert gs.ensure_daemon_running() is False
    assert not (state_dir / "daemon.pid").exists()


def test_ensure_daemon_running_noop_when_already_alive(state_dir: Path) -> None:
    """A live daemon means ensure_daemon_running() returns True without spawning."""
    gs = _gs()
    gs.init_global_state()
    gs.write_daemon_pid(os.getpid())
    gs.write_heartbeat()
    # Should NOT spawn a real daemon (we can't easily verify negative spawn,
    # but the function should return True quickly).
    assert gs.ensure_daemon_running() is True


def test_daemon_pid_round_trip(state_dir: Path) -> None:
    """write_daemon_pid → daemon_pid returns the exact int."""
    gs = _gs()
    gs.init_global_state()
    gs.write_daemon_pid(12345)
    assert gs.daemon_pid() == 12345
    gs.remove_daemon_pid()
    assert gs.daemon_pid() is None


def test_daemon_pid_malformed_returns_none(state_dir: Path) -> None:
    """A garbled pid file is treated as missing (not-alive)."""
    gs = _gs()
    gs.init_global_state()
    (state_dir / "daemon.pid").write_text("not-a-pid", encoding="utf-8")
    assert gs.daemon_pid() is None


# ---------- reload-flag helpers (Phase 1.6 of dispatch reads/clears these) --

def test_reload_flag_round_trip(state_dir: Path) -> None:
    """set → present, clear → absent. The flag survives until cleared."""
    gs = _gs()
    gs.init_global_state()
    assert gs.reload_flag_present() is False
    gs.set_reload_flag("test-plugin@mp")
    assert gs.reload_flag_present() is True
    gs.clear_reload_flag()
    assert gs.reload_flag_present() is False


def test_reload_flag_clear_idempotent(state_dir: Path) -> None:
    """clear_reload_flag on a missing flag is a silent no-op."""
    gs = _gs()
    gs.init_global_state()
    gs.clear_reload_flag()  # must not raise
    gs.clear_reload_flag()  # nor on the second call
    assert gs.reload_flag_present() is False


def test_reload_flag_stores_generation_and_reason(state_dir: Path) -> None:
    """The flag body is `<epoch-generation>\\t<reason>`: the generation drives
    per-session reload decisions, the reason is kept for diagnostic logs."""
    gs = _gs()
    gs.init_global_state()
    gs.set_reload_flag("plugin-a@mp,plugin-b@mp")
    body = (state_dir / "reload-needed.flag").read_text(encoding="utf-8")
    gen_str, _, reason = body.partition("\t")
    assert gen_str.isdigit() and int(gen_str) > 0, \
        f"body must start with an epoch generation, got {body!r}"
    assert reason == "plugin-a@mp,plugin-b@mp"
    assert gs.reload_generation() == int(gen_str)


def test_reload_generation_absent_and_legacy(state_dir: Path) -> None:
    """reload_generation(): absent → 0; a legacy boolean body (written by a daemon
    that predates the generation format) → 1, so a never-acked session still
    reloads exactly once instead of being stuck."""
    gs = _gs()
    gs.init_global_state()
    assert gs.reload_generation() == 0
    assert gs.reload_flag_present() is False
    # Legacy content: a bare reason string, no leading epoch line.
    (state_dir / "reload-needed.flag").write_text("ai-maestro-janitor@mp", encoding="utf-8")
    assert gs.reload_generation() == 1
    assert gs.reload_flag_present() is True


# ---------- daemon-restart staleness check ---------------------------------

def test_daemon_needs_restart_false_when_no_daemon(state_dir: Path) -> None:
    """No PID file → no daemon to restart → False."""
    gs = _gs()
    gs.init_global_state()
    assert gs.daemon_needs_restart() is False


def test_daemon_needs_restart_false_when_pid_dead(state_dir: Path) -> None:
    """A stale pid file (process gone) means there's nothing to restart."""
    gs = _gs()
    gs.init_global_state()
    gs.write_daemon_pid(999_999)
    assert gs.daemon_needs_restart() is False


def test_daemon_needs_restart_false_when_cmdline_matches(state_dir: Path) -> None:
    """Live PID whose cmdline contains the expected daemon path → no restart needed.

    Uses the pytest process itself as the "daemon": we cannot make pytest's
    argv contain daemon.py, so we monkey-patch _read_process_cmdline to
    return a synthetic argv that DOES include the expected path. The
    comparison logic is what's under test.
    """
    gs = _gs()
    gs.init_global_state()
    gs.write_daemon_pid(os.getpid())
    expected = str(gs.daemon_script_path().resolve())
    # Synthesize a matching argv around the expected path.
    gs._read_process_cmdline = lambda _pid: f"uv run --script --quiet {expected}"  # type: ignore[attr-defined]
    assert gs.daemon_needs_restart() is False


def test_daemon_needs_restart_true_when_cmdline_mismatches(state_dir: Path) -> None:
    """Live PID whose cmdline points at a different cache version → restart needed."""
    gs = _gs()
    gs.init_global_state()
    gs.write_daemon_pid(os.getpid())
    # Synthesize a stale-version argv (different path than the current cache).
    gs._read_process_cmdline = lambda _pid: (  # type: ignore[attr-defined]
        "uv run --script --quiet "
        "/Users/x/.claude/plugins/cache/x/ai-maestro-janitor/0.4.13/scripts/daemon.py"
    )
    assert gs.daemon_needs_restart() is True


def test_request_daemon_restart_no_daemon_returns_false(state_dir: Path) -> None:
    """Asking to restart a non-running daemon is a silent no-op (False)."""
    gs = _gs()
    gs.init_global_state()
    assert gs.request_daemon_restart() is False


# ---------- spawn throttle / backoff (audit finding 2) ---------------------
#
# spawn_daemon_detached() stamps daemon.spawn-attempt.ts; ensure_daemon_running()
# now READS that marker and refuses to re-spawn within the min-spawn window. This
# damps the "daemon dies on every start → every heartbeat re-spawns it" churn.
# We replace the real OS-forking spawn with a call-recorder so we observe the GATE
# decision (the fork itself is covered by the subprocess tests in test_daemon.py).


def _record_spawns(gs):
    """Swap spawn_daemon_detached for a recorder that also stamps the marker.

    Mirrors the real spawn's marker write (the throttle reads it) without forking
    a daemon. Returns the calls list.
    """
    calls: list[int] = []

    def _fake_spawn():
        calls.append(int(time.time()))
        gs.state.atomic_write(gs._spawn_marker_path(), str(int(time.time())))
        return 12345

    gs.spawn_daemon_detached = _fake_spawn  # type: ignore[assignment]
    return calls


def test_ensure_daemon_running_spawns_when_no_marker(state_dir: Path) -> None:
    """First call (dead daemon, no prior attempt) spawns and returns True."""
    gs = _gs()
    gs.init_global_state()
    calls = _record_spawns(gs)
    assert gs.ensure_daemon_running() is True
    assert len(calls) == 1, "first call with no marker must spawn exactly once"
    assert gs._spawn_marker_path().is_file(), "spawn must stamp the attempt marker"


def test_ensure_daemon_running_throttles_within_window(state_dir: Path) -> None:
    """A second call right after the first is throttled — no re-spawn, returns False.

    This is the core of the fix: a daemon that died on start does not get
    re-spawned by the immediately-following heartbeat fire.
    """
    gs = _gs()
    gs.init_global_state()
    calls = _record_spawns(gs)

    assert gs.ensure_daemon_running() is True   # first → spawns
    assert gs.ensure_daemon_running() is False  # second, within window → throttled
    assert len(calls) == 1, "second call within the min-spawn window must NOT re-spawn"


def test_ensure_daemon_running_respawns_after_window(
    state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Once the min-spawn window elapses, a re-spawn is allowed again.

    We shrink the window to 1 s via the env knob and age the marker past it, so
    the throttle clears and the next call spawns — proving the backoff recovers
    rather than permanently wedging spawns.
    """
    gs = _gs()
    gs.init_global_state()
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_DAEMON_MIN_SPAWN_INTERVAL", "1")
    calls = _record_spawns(gs)

    assert gs.ensure_daemon_running() is True   # first → spawns, stamps marker
    assert len(calls) == 1
    # Age the marker beyond the 1 s window without sleeping.
    gs.state.atomic_write(gs._spawn_marker_path(), str(int(time.time()) - 5))
    assert gs.ensure_daemon_running() is True   # window elapsed → spawns again
    assert len(calls) == 2, "spawn must be allowed once the window elapses"


def test_ensure_daemon_running_throttle_skipped_when_alive(state_dir: Path) -> None:
    """A live daemon short-circuits before the throttle — returns True, never spawns.

    Guards against a regression where the throttle gate would block the cheap
    already-alive fast path.
    """
    gs = _gs()
    gs.init_global_state()
    calls = _record_spawns(gs)
    gs.write_daemon_pid(os.getpid())
    gs.write_heartbeat()
    assert gs.ensure_daemon_running() is True
    assert calls == [], "must not spawn when the daemon is already alive"


# ---------- Pillar 0: wedged-daemon kill + crash-loop breaker (TRDD-7100178d) ----
#
# A WEDGED daemon (pid alive, heartbeat stale) still holds the singleton flock, so
# a plain respawn loses the flock race and exits — silent outage. _kill_wedged_daemon
# frees the flock; the crash-loop breaker stops feeding a die-on-start daemon.
# Real subprocesses, every one killed + reaped in finally (no leaks).


def _spawn_fake_daemon(tmp_path: Path) -> subprocess.Popen:
    """A REAL child whose argv ends in .../daemon.py (passes the wedge-kill cmdline
    gate) and sleeps long enough to look wedged. Caller MUST kill+reap in finally."""
    script = tmp_path / "daemon.py"
    script.write_text("import time\ntime.sleep(300)\n", encoding="utf-8")
    return subprocess.Popen(
        [sys.executable, str(script)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _reap(proc: subprocess.Popen) -> None:
    """Guaranteed cleanup: kill if alive, always reap (no zombie left behind)."""
    if proc.poll() is None:
        proc.kill()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def _stale_hb(gs) -> int:
    """A heartbeat timestamp older than the default staleness threshold."""
    return int(time.time()) - gs.DEFAULT_DAEMON_STALE_SECONDS - 60


def test_kill_wedged_refuses_own_pid(state_dir: Path) -> None:
    """The wedge-kill must NEVER target the calling process — pid==getpid() with a
    stale heartbeat (the per-session-test stand-in pattern) returns False untouched."""
    gs = _gs()
    gs.init_global_state()
    gs.write_daemon_pid(os.getpid())
    gs.write_heartbeat(_stale_hb(gs))
    assert gs._kill_wedged_daemon() is False  # and we are trivially still alive


def test_kill_wedged_refuses_dead_pid(state_dir: Path) -> None:
    """A dead pid needs no kill — the plain spawn path handles it; returns False."""
    gs = _gs()
    gs.init_global_state()
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait(timeout=10)                       # now certainly dead AND reaped
    gs.write_daemon_pid(child.pid)
    gs.write_heartbeat(_stale_hb(gs))
    assert gs._kill_wedged_daemon() is False


def test_kill_wedged_requires_stale_heartbeat(state_dir: Path, tmp_path: Path) -> None:
    """A FRESH heartbeat means not wedged — the daemon-shaped child must survive."""
    gs = _gs()
    gs.init_global_state()
    proc = _spawn_fake_daemon(tmp_path)
    try:
        gs.write_daemon_pid(proc.pid)
        gs.write_heartbeat()                     # fresh
        assert gs._kill_wedged_daemon() is False
        assert proc.poll() is None, "a fresh-heartbeat daemon must NOT be killed"
    finally:
        _reap(proc)


def test_kill_wedged_refuses_foreign_cmdline(state_dir: Path) -> None:
    """PID-REUSE guard: a stale-heartbeat pid whose live cmdline is NOT a janitor
    daemon (no 'daemon.py' in argv) must never be killed — collateral-damage rule."""
    gs = _gs()
    gs.init_global_state()
    proc = subprocess.Popen(                      # an innocent non-daemon process
        [sys.executable, "-c", "import time; time.sleep(300)"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        gs.write_daemon_pid(proc.pid)
        gs.write_heartbeat(_stale_hb(gs))
        assert gs._kill_wedged_daemon() is False
        assert proc.poll() is None, "an innocent (pid-reused) process must survive"
    finally:
        _reap(proc)


def test_kill_wedged_kills_real_wedged_daemon(state_dir: Path, tmp_path: Path) -> None:
    """The real thing: daemon-shaped child + stale heartbeat → SIGTERM kills it and
    the function reports True (zombie-aware — the unreaped child counts as gone
    because a dead process has already released the flock)."""
    gs = _gs()
    gs.init_global_state()
    proc = _spawn_fake_daemon(tmp_path)
    try:
        gs.write_daemon_pid(proc.pid)
        gs.write_heartbeat(_stale_hb(gs))
        assert gs._kill_wedged_daemon() is True
        assert proc.wait(timeout=10) is not None  # actually dead (and reaped here)
    finally:
        _reap(proc)


def test_kill_wedged_sigkill_escalation_on_stopped_process(
    state_dir: Path, tmp_path: Path,
) -> None:
    """A SIGSTOP'd wedge never DELIVERS the queued SIGTERM — the escalation to
    SIGKILL (which works on stopped processes) must finish the job. 🐌"""
    gs = _gs()
    gs.init_global_state()
    proc = _spawn_fake_daemon(tmp_path)
    try:
        time.sleep(0.3)                          # let the child reach its sleep
        os.kill(proc.pid, signal.SIGSTOP)        # wedge it for real
        gs.write_daemon_pid(proc.pid)
        gs.write_heartbeat(_stale_hb(gs))
        assert gs._kill_wedged_daemon() is True, "SIGKILL escalation must terminate a stopped wedge"
        assert proc.wait(timeout=10) is not None
    finally:
        _reap(proc)


def test_record_spawn_attempt_appends_and_prunes(state_dir: Path) -> None:
    """The spawn history is a ring: 25 recorded attempts keep only the newest 20."""
    gs = _gs()
    gs.init_global_state()
    for i in range(25):
        gs._record_spawn_attempt(now=1000 + i)
    lines = gs._spawn_history_path().read_text(encoding="utf-8").splitlines()
    assert len(lines) == gs._SPAWN_HISTORY_KEEP
    assert lines[-1] == "1024" and lines[0] == "1005"  # newest kept, oldest pruned


def test_crash_loop_active_truth_table(state_dir: Path) -> None:
    """Breaker trips at LIMIT recent attempts; old attempts and a missing file don't trip it."""
    gs = _gs()
    gs.init_global_state()
    now = int(time.time())
    hist = gs._spawn_history_path()
    assert gs._crash_loop_active(now=now) is False           # no history file
    recent = [str(now - 10 * i) for i in range(gs._CRASH_LOOP_SPAWN_LIMIT - 1)]
    gs.state.atomic_write(hist, "\n".join(recent))
    assert gs._crash_loop_active(now=now) is False           # LIMIT-1 recent → not tripped
    recent.append(str(now - 5))
    gs.state.atomic_write(hist, "\n".join(recent))
    assert gs._crash_loop_active(now=now) is True            # LIMIT recent → tripped
    old = [str(now - gs._CRASH_LOOP_WINDOW_S - 100 - i) for i in range(gs._CRASH_LOOP_SPAWN_LIMIT)]
    gs.state.atomic_write(hist, "\n".join(old))
    assert gs._crash_loop_active(now=now) is False           # aged out → self-reset


def test_ensure_daemon_refuses_spawn_when_crash_looping(state_dir: Path) -> None:
    """With the breaker tripped, ensure_daemon_running refuses to spawn (returns False)."""
    gs = _gs()
    gs.init_global_state()
    calls = _record_spawns(gs)
    now = int(time.time())
    gs.state.atomic_write(
        gs._spawn_history_path(),
        "\n".join(str(now - 10 * i) for i in range(gs._CRASH_LOOP_SPAWN_LIMIT)),
    )
    assert gs.ensure_daemon_running() is False
    assert calls == [], "no spawn may happen while the crash-loop breaker is tripped"


def test_ensure_daemon_kills_wedge_then_spawns(state_dir: Path, tmp_path: Path) -> None:
    """End-to-end Pillar 0: a wedged daemon-shaped child is killed AND a fresh spawn
    is issued in the same ensure_daemon_running call — the outage self-heals."""
    gs = _gs()
    gs.init_global_state()
    calls = _record_spawns(gs)
    proc = _spawn_fake_daemon(tmp_path)
    try:
        gs.write_daemon_pid(proc.pid)
        gs.write_heartbeat(_stale_hb(gs))        # wedged: pid alive + stale heartbeat
        assert gs.ensure_daemon_running() is True
        assert proc.wait(timeout=10) is not None, "the wedge must be dead"
        assert len(calls) == 1, "a replacement spawn must be issued after the kill"
    finally:
        _reap(proc)
