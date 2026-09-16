"""TRDD-V2U2ZECI: an unwritable heartbeat-fires.log must surface on stderr, not vanish silently."""

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
    """Point both project and global state at tmp dirs; reload dispatch + gs.

    Mirrors tests/test_dispatch_phases.py::env_isolation exactly — same isolation
    is needed here so this test never touches the real host's state.
    """
    project = tmp_path / "project"
    project.mkdir()
    global_dir = tmp_path / "janitor-global-state"

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(global_dir))
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path / "janitor-control"))
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))

    for mod in ("dispatch", "global_state", "state"):
        if mod in sys.modules:
            del sys.modules[mod]

    return {"project": project, "global_dir": global_dir}


def _import_dispatch():
    """Import scripts/dispatch.py without running main()."""
    import importlib.util as _u

    spec = _u.spec_from_file_location(
        "janitor_dispatch_fire_log_unwritable", str(_PROJECT_ROOT / "scripts" / "dispatch.py")
    )
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _capture(fn) -> tuple[str, str]:
    """Run fn() capturing stdout + stderr; return (stdout, stderr)."""
    out_buf, err_buf = StringIO(), StringIO()
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out_buf, err_buf
    try:
        fn()
    finally:
        sys.stdout, sys.stderr = old_out, old_err
    return out_buf.getvalue(), err_buf.getvalue()


def test_unwritable_fire_log_reports_on_stderr_and_the_fire_still_completes(
    env_isolation: dict,
) -> None:
    """`.janitor/logs/heartbeat-fires.log` pre-created as a DIRECTORY forces
    `state.log_line("heartbeat-fires", ...)` to raise IsADirectoryError. Before the
    TRDD-V2U2ZECI fix that exception was swallowed with a bare `pass`: the fire left
    no trace anywhere. The fix must write the failure to stderr while still letting
    the fire complete (kill-switch is set so `main()` self-disarms right after the
    fire stamp, without walking the full detector roster).
    """
    project = env_isolation["project"]
    (project / ".janitor" / "logs" / "heartbeat-fires.log").mkdir(parents=True)

    dispatch = _import_dispatch()
    import global_state as gs

    gs.init_global_state()
    gs.set_kill_switch("disarmed")

    out, err = _capture(dispatch.main)

    assert "heartbeat-fires log append failed" in err, err
    assert "IsADirectoryError" in err, err
    # the fire still completed and emitted its normal decision — telemetry failure
    # must never block a fire.
    assert out.strip() == "[janitor-self-disarm]", f"the fire must still complete, got {out!r}"


def _run_fire(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, log_as_directory: bool) -> tuple[str, str]:
    """Run one fire (kill-switch disarmed) in a fresh sandbox, optionally pre-creating
    heartbeat-fires.log as a directory first; return (stdout, stderr)."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    project = tmp_path / "project"
    project.mkdir()
    global_dir = tmp_path / "janitor-global-state"
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(global_dir))
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path / "janitor-control"))
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))
    for mod in ("dispatch", "global_state", "state"):
        if mod in sys.modules:
            del sys.modules[mod]

    if log_as_directory:
        (project / ".janitor" / "logs" / "heartbeat-fires.log").mkdir(parents=True)

    dispatch = _import_dispatch()
    import global_state as gs

    gs.init_global_state()
    gs.set_kill_switch("disarmed")

    return _capture(dispatch.main)


def test_quiet_token_contract_unchanged_by_an_unwritable_fire_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance item 3 of TRDD-V2U2ZECI: the new stderr diagnostic must not alter the
    quiet-token contract on stdout — a clean sandbox and a directory-clobbered
    heartbeat-fires.log sandbox must emit byte-identical stdout, exactly one bare
    `[janitor-...]` line, with the failure visible only on stderr."""
    clean_out, clean_err = _run_fire(tmp_path / "clean", monkeypatch, log_as_directory=False)
    dir_out, dir_err = _run_fire(tmp_path / "dir", monkeypatch, log_as_directory=True)

    assert clean_out == dir_out, (clean_out, dir_out)
    assert clean_out.strip() == "[janitor-self-disarm]", clean_out
    assert "heartbeat-fires log append failed" not in clean_err, clean_err

    assert "heartbeat-fires log append failed" in dir_err, dir_err
    assert "IsADirectoryError" in dir_err, dir_err
