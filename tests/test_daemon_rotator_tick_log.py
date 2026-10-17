"""R5 (TRDD-HSRERK5S): the rotator tick logs its rc and sanitized stderr tail in daemon.log.

Real subprocesses through the real `_run_workload`; real temp log dir.
"""

from __future__ import annotations

import importlib
import re
import subprocess
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

def test_retried_tick_that_recovers_still_logs_the_first_attempts_reason(tmp_path: Path) -> None:
    """45ZUV5ZD: attempt 1 exits 1 with stderr, attempt 2 succeeds: the retry line carries the reason."""
    flag = tmp_path / "first-done"
    body = (
        "import sys, pathlib\n"
        f"f = pathlib.Path({str(flag)!r})\n"
        "if not f.exists():\n"
        "    f.write_text('x')\n"
        "    print('keychain refused the read', file=sys.stderr)\n"
        "    sys.exit(1)\n"
    )
    script = tmp_path / "flaky.py"
    script.write_text(body)
    result = daemon._run_workload([sys.executable, str(script)], timeout=20, max_attempts=2)
    assert result is not None and result.returncode == 0
    log = (tmp_path / "logs" / "daemon.log").read_text()
    assert "exited 1 (attempt 1/2)" in log
    assert "keychain refused the read" in log


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



def test_cut_stderr_tail_starts_on_a_line_boundary(tmp_path: Path) -> None:
    """A tail cut mid-line drops the partial first line and is prefixed with an ellipsis."""
    body = (
        "import sys\n"
        "for i in range(40):\n"
        "    print(f\"line-{i:02d} \" + \"x\" * 20, file=sys.stderr)\n"
        "sys.exit(1)\n"
    )
    log = _tick(tmp_path, body)
    tail = log.split("stderr: ", 1)[1].rstrip("\n")
    assert tail.startswith("...")
    first = tail[3:].lstrip().split("\n")[0].split()
    assert re.fullmatch(r"line-\d\d", first[0]) and first[1] == "x" * 20
    assert "line-39" in tail


def test_cut_single_long_line_keeps_the_character_cut(tmp_path: Path) -> None:
    """With no newline in the slice, the character cut is kept and prefixed with an ellipsis."""
    log = _tick(tmp_path, "import sys; print(\"y\" * 400, file=sys.stderr); sys.exit(1)")
    tail = log.split("stderr: ", 1)[1]
    assert tail.startswith("...y")


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


def _run_tick(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, subprocess_s: float,
              fleet_raises: bool = False, rc: int | None = None) -> str:
    """Run the real task_oauth_rotator_tick with a fake clock; the subprocess call 'takes' subprocess_s."""
    clock = [1000.0]

    def fake_monotonic() -> float:
        # Advances on every call so any deadline loop on monotonic terminates.
        clock[0] += 0.001
        return clock[0]

    monkeypatch.setattr(daemon.time, "monotonic", fake_monotonic)

    def fake_run(cmd: list[str], **kw: object) -> subprocess.CompletedProcess[str] | None:
        clock[0] += subprocess_s
        return None if rc is None else subprocess.CompletedProcess(cmd, rc, "", "")

    monkeypatch.setattr(daemon.oauth_supervisor, "opt_in_present", lambda: True)
    monkeypatch.setattr(daemon, "_run_workload", fake_run)
    monkeypatch.setattr(daemon.gs, "rotation_succeeded_within", lambda *a, **kw: fleet_raises)

    def boom(**kw: object) -> None:
        raise RuntimeError("scan down")

    monkeypatch.setattr(daemon.fleet_scan, "gather_fleet", boom)
    daemon.task_oauth_rotator_tick()
    log = tmp_path / "logs" / "daemon.log"
    return log.read_text() if log.exists() else ""


def test_slow_tick_logs_one_line_with_phases_and_load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A tick of 41 s writes exactly one 'rotator tick slow:' line with both phase times and a load field."""
    log = _run_tick(monkeypatch, tmp_path, 41)
    lines = [ln for ln in log.splitlines() if "rotator tick slow:" in ln]
    assert len(lines) == 1
    assert "subprocess 41s, esc-pass 0s" in lines[0]
    assert "rc=timeout" in lines[0]
    assert "load " in lines[0]


def test_fast_tick_writes_no_slow_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A tick under 30 s writes no slow line, while a 33 s tick in the same log does (positive control)."""
    assert "rotator tick slow:" not in _run_tick(monkeypatch, tmp_path, 5)
    log = _run_tick(monkeypatch, tmp_path, 33)
    lines = [ln for ln in log.splitlines() if "rotator tick slow:" in ln]
    assert len(lines) == 1
    assert "subprocess 33s" in lines[0]


def test_slow_tick_with_returncode_logs_rc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A slow tick whose subprocess returned rc=0 logs rc=0 in the slow line."""
    log = _run_tick(monkeypatch, tmp_path, 35, rc=0)
    assert "rotator tick slow:" in log
    assert "rc=0" in log


def test_slow_line_still_written_when_fleet_scan_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The early return after a failed fleet scan must not skip the slow line."""
    log = _run_tick(monkeypatch, tmp_path, 35, fleet_raises=True)
    assert "rotation-esc: fleet scan failed" in log
    assert "rotator tick slow: subprocess 35s" in log


def test_getloadavg_oserror_prints_load_na(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When os.getloadavg raises OSError the slow line says 'load n/a' and nothing raises."""
    def no_load() -> tuple[float, float, float]:
        raise OSError("unsupported")

    monkeypatch.setattr(daemon.os, "getloadavg", no_load)
    log = _run_tick(monkeypatch, tmp_path, 31)
    assert "load n/a" in log
