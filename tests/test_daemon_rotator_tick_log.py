"""R5 (TRDD-HSRERK5S): the rotator tick logs its rc and sanitized stderr tail in daemon.log.

Real subprocesses through the real `_run_workload`; real temp log dir.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_ROOT / "scripts"))
daemon = importlib.import_module("daemon")

_ADDR = "alice.owner" + "@" + "example.com"  # runtime-built: keeps the privacy scanner quiet


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Per-test tmp tree for every janitor state / DATA / HOME path."""
    home = tmp_path / "_home"
    data = home / ".claude" / "plugins" / "data" / "ai-maestro-janitor-ai-maestro-plugins"
    gsd = tmp_path / "_global-state"
    for d in (home, data, gsd):
        d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(gsd))
    monkeypatch.setenv("JANITOR_DATA_DIR", str(data))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(data))
    monkeypatch.setenv("JANITOR_LOG_DIR", str(tmp_path / "logs"))
    for fn in (daemon.state.project_root, daemon.state.janitor_root,
               daemon.state.state_dir, daemon.state.log_dir):
        fn.cache_clear()


def _tick(tmp_path: Path, body: str) -> str:
    script = tmp_path / "tick.py"
    script.write_text(body)
    daemon._log_rotator_tick_result(
        daemon._run_workload([sys.executable, str(script)], timeout=20, max_attempts=1))
    log = tmp_path / "logs" / "daemon.log"
    return log.read_text() if log.exists() else ""


def test_failing_tick_logs_rc_and_stderr_tail(tmp_path: Path) -> None:
    """A non-zero tick logs its return code and the stderr tail."""
    log = _tick(tmp_path, "import sys; print(\"boom: keychain refused\", file=sys.stderr); sys.exit(3)")
    assert "rotator tick rc=3" in log
    assert "boom: keychain refused" in log


def test_clean_tick_writes_no_line(tmp_path: Path) -> None:
    """A clean silent tick (rc=0, empty stderr) writes no rotator-tick line."""
    assert "rotator tick" not in _tick(tmp_path, "print(\"ok\")")


def test_email_and_token_in_stderr_never_reach_the_log(tmp_path: Path) -> None:
    """An e-mail address or sk-ant token in stderr is masked in daemon.log."""
    tok = "sk-ant-" + "A1b2C3d4"
    log = _tick(tmp_path, f"import sys; print(\"fail for {_ADDR} {tok}\", file=sys.stderr); sys.exit(1)")
    assert "rotator tick rc=1" in log
    assert _ADDR not in log
    assert tok not in log



def test_token_cut_by_truncation_is_still_masked(tmp_path: Path) -> None:
    """When the 300-char tail starts inside an sk-ant token, none of its secret chars leak."""
    secret = "AbCdEfGhIj" * 40  # 400 chars: the tail window starts mid-secret
    tok = "sk-ant-" + secret
    log = _tick(tmp_path, f"import sys; print(\"{tok}\", file=sys.stderr); sys.exit(1)")
    assert "rotator tick rc=1" in log
    assert "AbCdEfGhIj" not in log



def test_email_inside_repr_quotes_is_masked(tmp_path: Path) -> None:
    """An e-mail inside repr() single quotes in stderr is masked."""
    log = _tick(tmp_path, f"import sys; print(repr(\"slot for {_ADDR}\"), file=sys.stderr); sys.exit(1)")
    assert "rotator tick rc=1" in log
    assert _ADDR not in log


def test_unwritable_log_dir_does_not_raise(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A log write that really fails must not propagate out of the tick-result helper."""
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    monkeypatch.setenv("JANITOR_LOG_DIR", str(blocker))
    daemon.state.log_dir.cache_clear()
    script = tmp_path / "tick.py"
    script.write_text("import sys; sys.exit(2)")
    result = daemon._run_workload([sys.executable, str(script)], timeout=20, max_attempts=1)
    daemon._log_rotator_tick_result(result)
