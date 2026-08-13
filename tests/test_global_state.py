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
    # The six mode flags now live at the FIXED control_dir() (ARCHITECTURE.md §7.1,
    # TRDD-QK7M2B0X), not global_state_dir() — isolate it too, or every test in this
    # file would share the real process's $HOME/.claude/janitor-control.
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path / "janitor-control"))
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


def test_singleton_dual_first_acquires_second_fails(state_dir: Path) -> None:
    """One process holding the singleton blocks every other acquire attempt."""
    gs = _gs()
    h1 = gs.acquire_singleton_dual()
    assert h1 is not None, "first acquire must succeed"
    try:
        h2 = gs.acquire_singleton_dual()
        assert h2 is None, "second acquire must be denied while h1 holds the lock"
    finally:
        gs.release_singleton_dual(h1)


def test_singleton_dual_released_lets_next_acquire(state_dir: Path) -> None:
    """Releasing the singleton lets a subsequent acquire succeed (no stale state)."""
    gs = _gs()
    h1 = gs.acquire_singleton_dual()
    assert h1 is not None
    gs.release_singleton_dual(h1)
    h2 = gs.acquire_singleton_dual()
    assert h2 is not None
    gs.release_singleton_dual(h2)


def test_singleton_dual_holds_every_era(state_dir: Path, tmp_path: Path) -> None:
    """The handle holds control_dir() AND the old global_state_dir() inode (TRDD-QK7M2B0X
    phase B step 2). A 0.6x daemon knows only the old inode, so a hold that skipped it
    would let both eras win their own lock and each believe it is the machine's single
    writer — the two-daemon condition §7.2 exists to prevent. Verified from a SEPARATE
    process because flock is per-open-file-description: an in-process probe of an inode we
    already hold would conflict with ourselves and prove nothing about a foreign peer."""
    gs = _gs()
    h = gs.acquire_singleton_dual()
    assert h is not None
    try:
        assert len(h) == 2, "distinct control/global-state dirs must yield two held inodes"
        for path in (
            gs.control_dir() / "daemon.flock",
            gs.global_state_dir() / "daemon.flock",
        ):
            probe = subprocess.run(
                [sys.executable, "-c", (
                    "import fcntl,sys\n"
                    "fd=open(sys.argv[1],'a+')\n"
                    "try:\n"
                    "    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)\n"
                    "except OSError:\n"
                    "    sys.exit(3)\n"
                    "sys.exit(0)\n"
                ), str(path)],
                timeout=10,
            )
            assert probe.returncode == 3, f"{path} must be HELD against a foreign process"
    finally:
        gs.release_singleton_dual(h)


def test_singleton_dual_loses_to_old_era_holder(state_dir: Path) -> None:
    """A 0.6x-era daemon holding ONLY the old global_state_dir() inode must still deny the
    new-code singleton — and the loser must release the control half it already took, so
    nothing leaks and a later acquire (after the old daemon exits) succeeds."""
    gs = _gs()
    gs.init_global_state()
    old_holder = subprocess.Popen(
        [sys.executable, "-c", (
            "import fcntl,sys,time\n"
            "fd=open(sys.argv[1],'a+')\n"
            "fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)\n"
            "print('held',flush=True)\n"
            "time.sleep(30)\n"
        ), str(gs.global_state_dir() / "daemon.flock")],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert old_holder.stdout is not None and old_holder.stdout.readline().strip() == "held"
        assert gs.acquire_singleton_dual() is None, "old-era holder must deny the dual acquire"
    finally:
        old_holder.kill()
        old_holder.wait(10)
    h = gs.acquire_singleton_dual()
    assert h is not None, "after the old daemon exits, the singleton must be acquirable — a leaked control-half fd would deny us here"
    gs.release_singleton_dual(h)


def test_singleton_dual_blocking_waits_then_takes_over(state_dir: Path) -> None:
    """blocking=True WAITS for a held singleton and acquires it once released — instead of
    returning None — so the L0 keepalive daemon idles rather than spawn→abort→respawn
    churning under launchd's KeepAlive while a session daemon holds the singleton
    (TRDD-71ABD7V7). flock is per-open-file-description, so a second open in this same
    process genuinely conflicts."""
    import threading

    gs = _gs()
    gs.init_global_state()
    holder = gs.acquire_singleton_dual()
    assert holder is not None
    assert gs.acquire_singleton_dual() is None, "non-blocking acquire must fail while held"

    result: dict[str, object] = {}
    started = threading.Event()

    def waiter() -> None:
        started.set()
        result["h"] = gs.acquire_singleton_dual(blocking=True)  # must BLOCK until released

    t = threading.Thread(target=waiter, daemon=True)
    t.start()
    assert started.wait(2)
    time.sleep(0.3)
    assert "h" not in result, "blocking acquire returned while the lock was still held"

    gs.release_singleton_dual(holder)  # now the waiter should wake and take over
    t.join(3)
    assert not t.is_alive(), "blocking acquire never returned after the lock was released"
    assert result.get("h") is not None
    gs.release_singleton_dual(result["h"])  # type: ignore[arg-type]


def test_singleton_sentinels_dual_write_and_era_reads(state_dir: Path) -> None:
    """pid + heartbeat land at BOTH eras' paths, and the readers see a stamp from EITHER
    era alone (TRDD-QK7M2B0X phase B step 2). The write side covers the OLD reader (a 0.6x
    session's `daemon_is_alive()` resolves only global_state_dir() — nothing reading-side
    can reach that code, so the new writer must publish there); the read side covers the
    OLD writer (a 0.6x daemon beats only the old path — a new-path-only read would call a
    healthy daemon dead and spawn-churn against its lock)."""
    gs = _gs()
    gs.init_global_state()
    gs.write_daemon_pid(os.getpid())
    gs.write_heartbeat(now=1_700_000_000)
    for base in (gs.control_dir(), gs.global_state_dir()):
        assert (base / "daemon.pid").read_text().strip() == str(os.getpid()), base
        assert (base / "daemon.heartbeat.ts").read_text().strip() == "1700000000", base

    # Old-writer direction: wipe, then stamp ONLY the old path — readers must still see it.
    gs.remove_daemon_pid()
    for base in (gs.control_dir(), gs.global_state_dir()):
        assert not (base / "daemon.pid").exists()
        (base / "daemon.heartbeat.ts").unlink()
    (gs.global_state_dir() / "daemon.pid").write_text(str(os.getpid()), encoding="utf-8")
    (gs.global_state_dir() / "daemon.heartbeat.ts").write_text("1700000042", encoding="utf-8")
    assert gs.daemon_pid() == os.getpid()
    assert gs.read_heartbeat() == 1_700_000_042


def test_daemon_pid_prefers_live_process_across_eras(state_dir: Path) -> None:
    """A stale pid at the first-probed era must not shadow the LIVE daemon's pid at
    another — first-found would report the dead one, `daemon_is_alive()` would say DEAD,
    and every session would spawn-churn against the held flock (the crash-loop lookalike
    that hid the previous singleton bug)."""
    gs = _gs()
    gs.init_global_state()
    (gs.control_dir() / "daemon.pid").parent.mkdir(parents=True, exist_ok=True)
    (gs.control_dir() / "daemon.pid").write_text("999999", encoding="utf-8")  # dead
    (gs.global_state_dir() / "daemon.pid").write_text(str(os.getpid()), encoding="utf-8")
    assert gs.daemon_pid() == os.getpid(), "the LIVE pid must win over a dead one at an earlier era"
    # With no live pid anywhere, the first found is still returned (stale ≠ absent).
    (gs.global_state_dir() / "daemon.pid").write_text("999998", encoding="utf-8")
    assert gs.daemon_pid() == 999_999


def test_foreign_era_daemons_detects_second_daemon(state_dir: Path) -> None:
    """A LIVE pid published at any era that is not self is reported `(era, pid)` — the
    detector that turns a silent double-daemon into an indexed finding. Dead pids and
    self are not findings."""
    gs = _gs()
    gs.init_global_state()
    assert gs.foreign_era_daemons(os.getpid()) == []
    (gs.global_state_dir() / "daemon.pid").write_text("999999", encoding="utf-8")  # dead
    assert gs.foreign_era_daemons(os.getpid()) == [], "a dead pid is stale litter, not a second daemon"
    (gs.global_state_dir() / "daemon.pid").write_text(str(os.getpid()), encoding="utf-8")
    assert gs.foreign_era_daemons(os.getpid()) == [], "self is never foreign"
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        (gs.global_state_dir() / "daemon.pid").write_text(str(other.pid), encoding="utf-8")
        assert gs.foreign_era_daemons(os.getpid()) == [("global-state", other.pid)]
    finally:
        other.kill()
        other.wait(10)


def test_detector_lock_is_single_writer(state_dir: Path, tmp_path: Path) -> None:
    """The per-project `detector.lock` (MF3, TRDD-X07E7HTN) serialises the daemon-vs-cron
    writer: while one holder has it, a second acquire on the SAME project state dir SKIPS
    (held=False), and once released a fresh acquire succeeds. flock is per-open-file-
    description, so two `os.open`s in this one process genuinely conflict — the same property
    the singleton-flock tests rely on."""
    gs = _gs()
    sd = tmp_path / "proj" / ".janitor" / "state"
    with gs.detector_lock(sd) as held1:
        assert held1 is True, "first acquire must hold the lock"
        assert (sd / "detector.lock").is_file(), "the lock file is created in the project state dir"
        with gs.detector_lock(sd) as held2:
            assert held2 is False, "the second writer must SKIP while the first holds it"
    with gs.detector_lock(sd) as held3:
        assert held3 is True, "released → a subsequent acquire succeeds"


def test_detector_lock_is_per_project_not_global(state_dir: Path, tmp_path: Path) -> None:
    """The lock is PER-PROJECT: holding it for one project's state dir never blocks another
    project's — so the daemon covering project A cannot starve the cron of project B."""
    gs = _gs()
    sd_a = tmp_path / "a" / ".janitor" / "state"
    sd_b = tmp_path / "b" / ".janitor" / "state"
    with gs.detector_lock(sd_a) as held_a:
        assert held_a is True
        with gs.detector_lock(sd_b) as held_b:
            assert held_b is True, "a different project's lock must be independently acquirable"


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
    """The flag body is provenance JSON (`set_at`/`by`/`pid`/`reason`, TRDD-QK7M2B0X):
    `set_at` drives per-session reload decisions, `reason` is kept for diagnostic logs."""
    gs = _gs()
    gs.init_global_state()
    gs.set_reload_flag("plugin-a@mp,plugin-b@mp")
    prov = gs.read_flag_provenance("reload-needed.flag")
    assert prov["set_at"] > 0, f"body must carry a positive set_at generation, got {prov!r}"
    assert prov["reason"] == "plugin-a@mp,plugin-b@mp"
    assert gs.reload_generation() == prov["set_at"]


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


# ---------- standalone-skills reload generation (TRDD-LQU7OXXV) -------------

def test_skills_reload_flag_round_trip(state_dir: Path) -> None:
    """set → present, clear → absent — the standalone-skills sibling of the
    plugin-reload flag."""
    gs = _gs()
    gs.init_global_state()
    assert gs.skills_reload_flag_present() is False
    gs.set_skills_reload_flag("via /janitor-global-reload-skills")
    assert gs.skills_reload_flag_present() is True
    gs.clear_skills_reload_flag()
    assert gs.skills_reload_flag_present() is False


def test_skills_reload_flag_stores_generation_and_reason(state_dir: Path) -> None:
    """Body is provenance JSON, in its OWN flag file — distinct from the plugin
    reload flag so a plugin update never forces a skills reload."""
    gs = _gs()
    gs.init_global_state()
    gs.set_skills_reload_flag("standalone-skill-x")
    prov = gs.read_flag_provenance("skills-reload-needed.flag")
    assert prov["set_at"] > 0, f"expected a positive set_at generation, got {prov!r}"
    assert prov["reason"] == "standalone-skill-x"
    assert gs.skills_reload_generation() == prov["set_at"]
    # The two reload generations are independent files: stamping skills must NOT
    # create the plugin reload flag.
    assert gs.reload_generation() == 0


def test_skills_reload_generation_absent_and_legacy(state_dir: Path) -> None:
    """skills_reload_generation(): absent → 0; a legacy non-epoch body → 1 (a
    never-acked session still reloads exactly once instead of being stuck)."""
    gs = _gs()
    gs.init_global_state()
    assert gs.skills_reload_generation() == 0
    (state_dir / "skills-reload-needed.flag").write_text("reload please", encoding="utf-8")
    assert gs.skills_reload_generation() == 1
    assert gs.skills_reload_flag_present() is True


def test_skills_reload_clear_idempotent(state_dir: Path) -> None:
    """clear_skills_reload_flag on a missing flag is a silent no-op."""
    gs = _gs()
    gs.init_global_state()
    gs.clear_skills_reload_flag()  # must not raise
    gs.clear_skills_reload_flag()
    assert gs.skills_reload_flag_present() is False


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


def test_daemon_needs_restart_false_for_os_keepalive_daemon(state_dir: Path) -> None:
    """The OS-spawned (L0) daemon runs the stable entry daemon_keepalive_entry.py from the
    FIXED DATA path, so its argv never contains a cache daemon.py path. It MUST be exempt
    from the staleness check — otherwise every heartbeat would mark it stale + SIGTERM it,
    launchd would respawn it, and the next heartbeat would SIGTERM it again: an endless
    restart loop (TRDD-71ABD7V7)."""
    gs = _gs()
    gs.init_global_state()
    gs.write_daemon_pid(os.getpid())
    # A keepalive-entry argv that does NOT contain the expected cache daemon.py path.
    gs._read_process_cmdline = lambda _pid: (  # type: ignore[attr-defined]
        "/usr/bin/python3 "
        "/Users/x/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/scripts/daemon_keepalive_entry.py "
        "--keepalive"
    )
    assert gs.daemon_needs_restart() is False


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


def test_record_graceful_exit_appends_and_prunes(state_dir: Path) -> None:
    """The graceful-exit history is a ring: 25 recorded exits keep only the newest 20."""
    gs = _gs()
    gs.init_global_state()
    for i in range(25):
        gs.record_graceful_exit(now=1000 + i)
    lines = gs._graceful_exit_history_path().read_text(encoding="utf-8").splitlines()
    assert len(lines) == gs._GRACEFUL_EXIT_KEEP
    assert lines[-1] == "1024" and lines[0] == "1005"  # newest kept, oldest pruned


def test_spawn_has_graceful_predecessor(state_dir: Path) -> None:
    """A spawn within the grace window AFTER a graceful exit is attributed to it;
    one before it, or too far after it, is not."""
    gs = _gs()
    assert gs._spawn_has_graceful_predecessor(1010, [1000], grace_s=30) is True
    assert gs._spawn_has_graceful_predecessor(1000, [1000], grace_s=30) is True   # boundary: 0s after
    assert gs._spawn_has_graceful_predecessor(1030, [1000], grace_s=30) is True   # boundary: exactly grace_s
    assert gs._spawn_has_graceful_predecessor(1031, [1000], grace_s=30) is False  # 1s past the window
    assert gs._spawn_has_graceful_predecessor(990, [1000], grace_s=30) is False   # spawn BEFORE the exit
    assert gs._spawn_has_graceful_predecessor(1010, [], grace_s=30) is False      # no graceful exits at all


def test_crash_loop_breaker_ignores_orderly_sigterm_burst(state_dir: Path) -> None:
    """janitor#216: N spawns each immediately following a LOGGED graceful exit
    (an operator launchctl bootout/bootstrap burst, or a mutual-kill ping-pong)
    must NOT trip the breaker — even though the RAW spawn count alone would."""
    gs = _gs()
    gs.init_global_state()
    now = int(time.time())
    # _CRASH_LOOP_SPAWN_LIMIT spawns, 60s apart, each preceded by a graceful exit
    # a few seconds earlier — the exact shape of the #216/#211 SIGTERM ping-pong.
    spawn_epochs = [now - 60 * (gs._CRASH_LOOP_SPAWN_LIMIT - i) for i in range(gs._CRASH_LOOP_SPAWN_LIMIT)]
    graceful_epochs = [s - 5 for s in spawn_epochs]
    gs.state.atomic_write(gs._spawn_history_path(), "\n".join(str(s) for s in spawn_epochs))
    gs.state.atomic_write(gs._graceful_exit_history_path(), "\n".join(str(g) for g in graceful_epochs))
    # Sanity: the same raw spawn count WOULD trip the old (pre-#216) predicate.
    raw = gs._spawn_history_path().read_text(encoding="utf-8")
    recent = [ln for ln in raw.splitlines() if now - int(ln) <= gs._CRASH_LOOP_WINDOW_S]
    assert len(recent) >= gs._CRASH_LOOP_SPAWN_LIMIT
    assert gs._crash_loop_active(now=now) is False, "orderly SIGTERM churn must not read as a crash loop"


def test_crash_loop_breaker_still_trips_on_unattributed_spawns(state_dir: Path) -> None:
    """janitor#216 must not fail OPEN: spawns with NO logged graceful predecessor
    (the actual crash-on-start case) still trip the breaker exactly as before."""
    gs = _gs()
    gs.init_global_state()
    now = int(time.time())
    spawn_epochs = [now - 10 * i for i in range(gs._CRASH_LOOP_SPAWN_LIMIT)]
    gs.state.atomic_write(gs._spawn_history_path(), "\n".join(str(s) for s in spawn_epochs))
    # No graceful-exit-history file at all — every spawn is unattributed.
    assert gs._crash_loop_active(now=now) is True


def test_crash_loop_breaker_trips_when_graceful_exit_too_stale(state_dir: Path) -> None:
    """A graceful exit long before the grace window does not launder a later,
    otherwise-unexplained spawn burst into looking orderly."""
    gs = _gs()
    gs.init_global_state()
    now = int(time.time())
    spawn_epochs = [now - 10 * i for i in range(gs._CRASH_LOOP_SPAWN_LIMIT)]
    gs.state.atomic_write(gs._spawn_history_path(), "\n".join(str(s) for s in spawn_epochs))
    stale_graceful = now - gs._GRACEFUL_EXIT_GRACE_S - 3600  # an hour past any spawn's grace window
    gs.state.atomic_write(gs._graceful_exit_history_path(), str(stale_graceful))
    assert gs._crash_loop_active(now=now) is True


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


# ---------- maintenance-mode flag (TRDD-FPL60EKV) ----------


def test_maintenance_mode_setter_and_reader_are_gone(state_dir: Path) -> None:
    """INVERTED (owner directive 2026-07-31). Maintenance mode kept every session's cron firing
    and the daemon resident while doing none of the work, so a quiesced fleet looked exactly
    like a healthy one. The flag can no longer be SET or READ — only cleared.

    The asymmetry is the point and mirrors the pause removal: keeping a reader would let some
    future branch honour a flag nothing can legitimately set, which is how a retired switch
    comes back to life."""
    gs = _gs()
    assert not hasattr(gs, "set_maintenance_mode")
    assert not hasattr(gs, "maintenance_mode_present")
    assert callable(gs.clear_maintenance_mode), "the migration sweep must survive"


def test_retired_maintenance_flag_is_swept_from_disk(state_dir: Path) -> None:
    """MIGRATION, and it is load-bearing: real hosts have `maintenance-mode.flag` on disk right
    now, and the lever that used to lift it (/janitor-global-maintenance-off) went away with the
    mode. `clear_maintenance_mode` is what every arm calls so an upgraded machine does not keep
    looking suspended forever, with nothing left able to un-suspend it."""
    gs = _gs()
    gs.init_global_state()
    flag = gs.control_dir() / "maintenance-mode.flag"
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("set by an older janitor\n", encoding="utf-8")
    gs.clear_maintenance_mode()
    assert not flag.exists(), "an arm must remove a flag an older version left behind"


def test_maintenance_clear_idempotent_and_leaves_the_kill_switch_alone(state_dir: Path) -> None:
    """Clearing an absent flag is a safe no-op, and sweeping the RETIRED flag must never touch
    the one machine-wide switch that still exists — an arm sweeps litter, it does not revive a
    deliberately disarmed fleet."""
    gs = _gs()
    gs.init_global_state()
    gs.clear_maintenance_mode()  # must not raise even though nothing is set
    gs.set_kill_switch("k")
    gs.clear_maintenance_mode()
    assert gs.kill_switch_present() is True, "the sweep must not clear the kill-switch"


# ---------- daemon-restart RECENCY gate (audit B-2 / CC 2.1.200) ----------
#
# _restart_decision is the PURE core of daemon_needs_restart: given the running
# daemon's argv, the current-cache daemon.py path, and the quarantined-version
# set, it decides whether to SIGTERM-and-respawn. Tested with REAL cache-shaped
# path strings (no process, no mock) so the version DIRECTIONALITY is pinned
# exactly — an OLDER reinstalled cache must NOT seize a NEWER running daemon.


def _daemon_path(version: str, *, home: str = "/u") -> str:
    """A realistic cache `daemon.py` argv (uv-run form) for a plugin version."""
    return (
        f"uv run --script --quiet {home}/.claude/plugins/cache/ai-maestro-plugins/"
        f"ai-maestro-janitor/{version}/scripts/daemon.py"
    )


def _daemon_bare(version: str, *, home: str = "/u") -> str:
    """The bare resolved `daemon.py` path (the shape `daemon_script_path()` yields)."""
    return _daemon_path(version, home=home).split()[-1]


def test_daemon_needs_restart_newer_current_restarts_older(state_dir: Path) -> None:
    """Roll-forward: the heartbeat's cache is NEWER than the running daemon → restart (True)."""
    gs = _gs()
    assert gs._restart_decision(_daemon_path("0.30.0"), _daemon_bare("0.31.0"), set()) is True


def test_daemon_needs_restart_older_current_does_not_restart_newer(state_dir: Path) -> None:
    """B-2 guard: an OLDER heartbeat must NOT SIGTERM a NEWER running daemon (False)."""
    gs = _gs()
    assert gs._restart_decision(_daemon_path("0.31.0"), _daemon_bare("0.30.0"), set()) is False


def test_daemon_needs_restart_same_version_does_not_restart(state_dir: Path) -> None:
    """Same version, path differs only in install location → no code change, no restart (False)."""
    gs = _gs()
    running = _daemon_path("0.31.0", home="/opt/other")
    expected = _daemon_bare("0.31.0", home="/u")
    assert expected not in running, "precondition: not an exact-substring match"
    assert gs._restart_decision(running, expected, set()) is False


def test_daemon_needs_restart_quarantined_newer_may_roll_down(state_dir: Path) -> None:
    """C3 rollback DOWN: an older heartbeat MAY restart a newer daemon iff it is quarantined (True)."""
    gs = _gs()
    assert gs._restart_decision(_daemon_path("0.31.0"), _daemon_bare("0.30.0"), {"0.31.0"}) is True


def test_daemon_needs_restart_exact_path_match_no_restart(state_dir: Path) -> None:
    """The running argv already carries the current daemon.py path → nothing to roll (False)."""
    gs = _gs()
    expected = _daemon_bare("0.31.0")
    running = _daemon_path("0.31.0")
    assert expected in running
    assert gs._restart_decision(running, expected, set()) is False


def test_daemon_needs_restart_unparseable_path_fails_safe_true(state_dir: Path) -> None:
    """No cache-version segment in one path → fail-safe to the pre-B-2 'roll on any diff' (True)."""
    gs = _gs()
    assert gs._restart_decision("python /opt/custom/install/daemon.py", _daemon_bare("0.31.0"), set()) is True


# ---- TRDD-DB1P25S4 / janitor#211: own-stable-daemon guards + deciding-version ----
# quarantine. The keepalive entry and the DATA-staged daemon.py run from FIXED,
# version-less paths, so the unparseable-version fail-safe above used to SIGTERM
# them on EVERY fire (ticket T-RVZX688P's eviction loop); and neither roll
# direction may reseat the daemon on a QUARANTINED deciding version (the #211
# ping-pong that falsely tripped the crash-loop breaker).

_KEEPALIVE_CMDLINE = (
    "/u/.local/share/uv/python/cpython-3.12-macos-aarch64-none/bin/python3.12 "
    "/u/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins"
    "/scripts/daemon_keepalive_entry.py --keepalive"
)
_DATA_DAEMON_CMDLINE = (
    "python3.12 /u/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins"
    "/scripts/daemon.py"
)


def test_keepalive_launched_daemon_is_never_evicted(state_dir: Path) -> None:
    """A keepalive-launched daemon (version-less FIXED DATA argv) is never evicted — in any
    roll direction, quarantined or not (the pure-core guard the agentlens report §7 asked for)."""
    gs = _gs()
    assert gs._restart_decision(_KEEPALIVE_CMDLINE, _daemon_bare("2.4.1"), set()) is False
    assert gs._restart_decision(_KEEPALIVE_CMDLINE, _daemon_bare("2.4.1"), {"2.4.1"}) is False
    assert gs._restart_decision(_KEEPALIVE_CMDLINE, _daemon_bare("2.3.0"), set()) is False


def test_data_staged_daemon_is_never_evicted(state_dir: Path) -> None:
    """The DATA-staged daemon.py (direct-interpreter plist / hand-spawn shape) is the same
    class as the keepalive entry: version-less BUT re-staged from the live cache by
    construction — the argv-mismatch SIGTERM on this shape is what undid the TCC hot fix."""
    gs = _gs()
    assert gs._restart_decision(_DATA_DAEMON_CMDLINE, _daemon_bare("2.4.1"), set()) is False
    assert gs._restart_decision(_DATA_DAEMON_CMDLINE, _daemon_bare("2.3.0"), {"2.4.1"}) is False


def test_roll_forward_into_quarantined_version_is_refused(state_dir: Path) -> None:
    """janitor#211 forward half: a NEWER-but-QUARANTINED deciding cache must not SIGTERM a
    healthy older daemon to reseat itself; with a clean decider roll-forward is unchanged."""
    gs = _gs()
    assert gs._restart_decision(_daemon_path("2.3.0"), _daemon_bare("2.4.1"), {"2.4.1"}) is False
    assert gs._restart_decision(_daemon_path("2.3.0"), _daemon_bare("2.4.1"), set()) is True


def test_roll_down_onto_quarantined_decider_is_refused(state_dir: Path) -> None:
    """janitor#211 symmetry: rolling DOWN is legitimate only onto a known-good version — when
    the deciding older version is itself quarantined, let the running daemon stand."""
    gs = _gs()
    assert (
        gs._restart_decision(_daemon_path("2.4.1"), _daemon_bare("2.3.0"), {"2.4.1", "2.3.0"})
        is False
    )


# ---- managed-interpreter resolution for the daemon spawn (TRDD-DB1P25S4) ----
# TCC persists an Automation grant only against a STABLE binary identity; `uv run
# --script` mints an ephemeral per-spawn python shim, so the spawn must prefer uv's
# MANAGED CPython and fall back to the shim only when none resolves.


def test_managed_python_path_returns_validated_path(
    state_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`uv python find --system --managed-python <pin>` success → its stdout path, provided
    it is a real executable. `--system` is LOAD-BEARING (without it a project's .venv wins,
    a cwd-dependent identity); both flags must be on the argv."""
    gs = _gs()
    fake_py = tmp_path / "python3.12"
    fake_py.write_text("#!/bin/sh\n", encoding="utf-8")
    fake_py.chmod(0o755)
    seen: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # noqa: ANN001, ANN003
        seen.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout=f"{fake_py}\n", stderr="")

    monkeypatch.setattr(gs.subprocess, "run", fake_run)
    assert gs._managed_python_path() == str(fake_py)
    assert seen and "--system" in seen[0] and "--managed-python" in seen[0]


def test_managed_python_path_none_on_failure(
    state_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No uv, a failing find, or a non-executable result → None (callers fall back)."""
    gs = _gs()

    def raising_run(cmd, **kwargs):  # noqa: ANN001, ANN003
        raise FileNotFoundError("no uv")

    monkeypatch.setattr(gs.subprocess, "run", raising_run)
    assert gs._managed_python_path() is None

    def failing_run(cmd, **kwargs):  # noqa: ANN001, ANN003
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="no interpreter found")

    monkeypatch.setattr(gs.subprocess, "run", failing_run)
    assert gs._managed_python_path() is None

    ghost = tmp_path / "not-there" / "python3.12"

    def ghost_run(cmd, **kwargs):  # noqa: ANN001, ANN003
        return subprocess.CompletedProcess(cmd, 0, stdout=f"{ghost}\n", stderr="")

    monkeypatch.setattr(gs.subprocess, "run", ghost_run)
    assert gs._managed_python_path() is None


class _FakeProc:
    pid = 4242


def _is_daemon_spawn(argv: list[str]) -> bool:
    """True iff this argv launches the daemon (under any of the launcher candidates)."""
    return any(str(a).endswith("daemon.py") for a in argv)


def _daemon_spawn_spy(gs, calls: list[list[str]], *, fail_first: bool = False):  # noqa: ANN001
    """A `subprocess.Popen` double scoped to the DAEMON SPAWN, delegating everything else.

    `monkeypatch.setattr(gs.subprocess, "Popen", ...)` patches the stdlib MODULE object, so
    a naive fake intercepts every Popen in the process — including the
    `subprocess.run(["git", "rev-parse", "--show-toplevel"])` inside `state.project_root()`,
    which `spawn_daemon_detached`'s error path reaches via `state.log_line`. That produced
    two distinct failures: the git call landed in `calls` and inflated the count, and
    `subprocess.run` needs the context-manager protocol that a `pid`-only stub does not have.

    Latent until 2026-08-13, and worth remembering WHY: `project_root()` is `@lru_cache`d, so
    a cache warmed by an earlier test skipped the git call entirely and the suite stayed
    green. Closing the TRDD-TSTISOL1 isolation leak — which clears that cache per test —
    removed the MASK, not the bug. Delegating non-spawn commands to the real Popen fixes it
    properly; re-warming the cache would only hide it again.
    """
    real_popen = gs.subprocess.Popen

    def fake_popen(cmd, **kwargs):  # noqa: ANN001, ANN003
        argv = [str(a) for a in cmd]
        if not _is_daemon_spawn(argv):
            return real_popen(cmd, **kwargs)
        calls.append(argv)
        if fail_first and len(calls) == 1:
            raise FileNotFoundError("interpreter vanished")
        return _FakeProc()

    return fake_popen


def test_spawn_prefers_managed_interpreter(
    state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """spawn_daemon_detached launches daemon.py under the MANAGED interpreter when one
    resolves — the daemon (and its osascript children, which inherit sys.executable) then
    carry the TCC-granted stable identity instead of the ungrantable uv shim."""
    gs = _gs()
    calls: list[list[str]] = []
    monkeypatch.setattr(gs, "_managed_python_path", lambda: "/stable/python3.12")
    monkeypatch.setattr(gs.subprocess, "Popen", _daemon_spawn_spy(gs, calls))
    assert gs.spawn_daemon_detached() == 4242
    assert calls[0][0] == "/stable/python3.12"
    assert calls[0][1].endswith("daemon.py")


def test_spawn_falls_back_to_uv_run_without_managed(
    state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No managed interpreter → `uv run --script` remains the launcher (a running daemon
    beats none, even under the ephemeral identity)."""
    gs = _gs()
    calls: list[list[str]] = []
    monkeypatch.setattr(gs, "_managed_python_path", lambda: None)
    monkeypatch.setattr(gs.subprocess, "Popen", _daemon_spawn_spy(gs, calls))
    assert gs.spawn_daemon_detached() == 4242
    assert calls[0][:4] == ["uv", "run", "--script", "--quiet"]


def test_spawn_skips_failing_launcher(
    state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A launcher that cannot exec (OSError) is skipped, not fatal — the next candidate
    in the managed → uv-run → sys.executable ladder is tried."""
    gs = _gs()
    calls: list[list[str]] = []
    monkeypatch.setattr(gs, "_managed_python_path", lambda: "/stable/python3.12")
    monkeypatch.setattr(gs.subprocess, "Popen", _daemon_spawn_spy(gs, calls, fail_first=True))
    assert gs.spawn_daemon_detached() == 4242
    assert calls[0][0] == "/stable/python3.12"
    assert calls[1][:4] == ["uv", "run", "--script", "--quiet"]


def test_daemon_needs_restart_no_daemon_returns_false(state_dir: Path) -> None:
    """No daemon pid on disk → daemon_needs_restart is False (nothing to restart)."""
    gs = _gs()
    gs.init_global_state()
    assert gs.daemon_needs_restart() is False


def test_daemon_needs_restart_non_cache_path_fails_safe_true(
    state_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end (real child + real ps + real read_quarantine): a live daemon whose argv
    carries NO cache version segment hits the fail-safe → daemon_needs_restart True."""
    monkeypatch.setenv("JANITOR_DATA_DIR", str(tmp_path / "data"))  # hermetic quarantine read
    gs = _gs()
    gs.init_global_state()
    proc = _spawn_fake_daemon(tmp_path)  # argv ends in <tmp>/daemon.py (no cache version)
    try:
        gs.write_daemon_pid(proc.pid)
        assert gs.daemon_needs_restart() is True
    finally:
        _reap(proc)


# --------------------------------------------------------------------------- #
# Persistent arm state (TRDD-TUIBWHT7) — "arm once, armed forever"
# --------------------------------------------------------------------------- #


def test_armed_state_absent_by_default(state_dir: Path) -> None:
    """Never armed, never disarmed → "absent" (the genuinely-first-install case)."""
    gs = _gs()
    gs.init_global_state()
    assert gs.armed_state() == "absent"


def test_armed_state_round_trip(state_dir: Path) -> None:
    """record_armed() → "armed"; clear_armed() → back to "absent"."""
    gs = _gs()
    gs.init_global_state()
    gs.record_armed("arm")
    assert gs.armed_state() == "armed"
    gs.clear_armed()
    assert gs.armed_state() == "absent"


def test_armed_state_clear_is_idempotent(state_dir: Path) -> None:
    """clear_armed() on an already-absent flag is a silent no-op."""
    gs = _gs()
    gs.init_global_state()
    gs.clear_armed()  # must not raise
    gs.clear_armed()  # nor on the second call
    assert gs.armed_state() == "absent"


def test_armed_state_kill_switch_always_wins(state_dir: Path) -> None:
    """A machine-wide STOP reads as "disarmed" even while `armed.flag` is still present — a
    stray flag left by a crashed disarm must never make a stopped machine look armed."""
    gs = _gs()
    gs.init_global_state()
    gs.record_armed("arm")
    assert gs.armed_state() == "armed"
    gs.set_kill_switch("test")
    assert gs.armed_state() == "disarmed", "the kill-switch must override a present armed.flag"
    gs.clear_kill_switch()
    assert gs.armed_state() == "armed", "clearing the stop reveals the still-present arm claim"


def test_record_armed_stores_provenance(state_dir: Path) -> None:
    """The flag body is provenance JSON, same shape as every other control-plane flag."""
    gs = _gs()
    gs.init_global_state()
    gs.record_armed("arm")
    prov = gs.read_flag_provenance("armed.flag")
    assert prov["set_at"] > 0, f"body must carry a positive set_at, got {prov!r}"
    assert prov["reason"] == "arm"
