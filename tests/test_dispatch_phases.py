"""Tests for the new dispatch phases — `[janitor-reload]` emission and the
daemon-restart-if-stale check.

We exercise the phases in-process by importing dispatch.py as a module and
calling the underscore-private helpers directly. The full dispatch.main()
isn't appropriate here because it also walks the detector roster; we want
fast, focused tests on just the two new phases.

Per-test isolation: $JANITOR_GLOBAL_STATE_DIR + $CLAUDE_PROJECT_DIR both
point at tmp_path so the user's real state is never touched.
"""

from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))


@pytest.fixture
def env_isolation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Point both project and global state at tmp dirs; reload dispatch + gs."""
    project = tmp_path / "project"
    project.mkdir()
    global_dir = tmp_path / "janitor-global-state"

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(global_dir))

    # Force-reload so module-level path resolution picks up the env.
    for mod in ("dispatch", "global_state", "state"):
        if mod in sys.modules:
            del sys.modules[mod]

    return {"project": project, "global_dir": global_dir}


def _import_dispatch():
    """Import scripts/dispatch.py without running main()."""
    import importlib.util as _u
    spec = _u.spec_from_file_location(
        "janitor_dispatch_under_test",
        str(_PROJECT_ROOT / "scripts" / "dispatch.py"),
    )
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _capture_stdout(fn):
    """Run fn() while capturing print() output. Return captured string."""
    buf = StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        fn()
    finally:
        sys.stdout = old
    return buf.getvalue()


# ---------- Phase 1.6: plugin reload --------------------------------------

def test_phase_plugin_reload_silent_when_flag_absent(env_isolation: dict) -> None:
    """No reload-needed.flag → no marker emitted, no log lines."""
    dispatch = _import_dispatch()
    import global_state as gs
    gs.init_global_state()
    assert gs.reload_flag_present() is False

    out = _capture_stdout(dispatch._phase_plugin_reload)
    assert out == "", f"phase must be silent when no flag is set, got {out!r}"


def test_phase_plugin_reload_emits_marker_and_clears_flag(env_isolation: dict) -> None:
    """flag present → bare [janitor-reload] line emitted, flag cleared."""
    dispatch = _import_dispatch()
    import global_state as gs
    gs.init_global_state()
    gs.set_reload_flag("ai-maestro-janitor@ai-maestro-plugins")

    out = _capture_stdout(dispatch._phase_plugin_reload)
    assert out.strip() == "[janitor-reload]", \
        f"phase must emit exactly the bare marker, got {out!r}"
    assert gs.reload_flag_present() is False, \
        "phase must clear the flag after emission so the marker fires only once"


def test_phase_plugin_reload_idempotent_within_same_fire(env_isolation: dict) -> None:
    """Calling the phase twice in a row only emits one marker (flag self-clears).

    A second consecutive call (without the daemon re-arming the flag in between)
    must produce empty output — the dispatch is line-driven; one marker per
    real update event.
    """
    dispatch = _import_dispatch()
    import global_state as gs
    gs.init_global_state()
    gs.set_reload_flag("plugin@mp")

    first = _capture_stdout(dispatch._phase_plugin_reload).strip()
    second = _capture_stdout(dispatch._phase_plugin_reload).strip()
    assert first == "[janitor-reload]"
    assert second == ""


# ---------- Phase 1.65: daemon restart if stale ---------------------------

def test_phase_daemon_restart_no_daemon_is_noop(env_isolation: dict) -> None:
    """No running daemon → phase is a silent no-op (never raises)."""
    dispatch = _import_dispatch()
    import global_state as gs
    gs.init_global_state()
    # No pid file → daemon_needs_restart returns False → no SIGTERM attempted.
    dispatch._phase_daemon_restart_if_stale()  # must not raise


def test_phase_daemon_restart_sends_sigterm_on_mismatch(env_isolation: dict) -> None:
    """When daemon_needs_restart returns True, the phase delivers SIGTERM.

    We use a spawned `sleep` subprocess as a controllable stand-in for the
    daemon: it's a real OS process we can write into daemon.pid, and we
    monkey-patch _read_process_cmdline to return a path that mismatches
    the expected one. SIGTERM brings sleep down within milliseconds.
    """
    import subprocess as _sp
    dispatch = _import_dispatch()
    import global_state as gs
    gs.init_global_state()

    # Spawn a real, controllable child process.
    sleeper = _sp.Popen(["sleep", "30"], stdin=_sp.DEVNULL, stdout=_sp.DEVNULL,
                        stderr=_sp.DEVNULL)
    try:
        gs.write_daemon_pid(sleeper.pid)
        # Synthesize a "stale" argv so daemon_needs_restart returns True.
        gs._read_process_cmdline = lambda _pid: (  # type: ignore[attr-defined]
            "uv run --script --quiet /old/cache/0.4.0/scripts/daemon.py"
        )
        assert gs.daemon_needs_restart() is True

        dispatch._phase_daemon_restart_if_stale()

        # SIGTERM should bring the sleep child down quickly.
        try:
            sleeper.wait(timeout=5.0)
        except _sp.TimeoutExpired:
            sleeper.kill()
            pytest.fail("phase did not SIGTERM the stale daemon")
        assert sleeper.returncode is not None
    finally:
        if sleeper.poll() is None:
            sleeper.kill()
            sleeper.wait(timeout=2.0)


def test_phase_daemon_restart_swallows_exceptions(env_isolation: dict) -> None:
    """If daemon_needs_restart raises, the phase logs and continues (no crash).

    Monkey-patch the function on the *imported gs module inside dispatch*
    so the wrap is exercised.
    """
    dispatch = _import_dispatch()
    # Make daemon_needs_restart blow up; phase must NOT propagate.
    def _boom() -> bool:
        raise RuntimeError("simulated filesystem failure")
    dispatch.gs.daemon_needs_restart = _boom  # type: ignore[assignment]
    dispatch._phase_daemon_restart_if_stale()  # must not raise
