"""A crashed xdist worker must fail the publish pytest gate, never hang it (TRDD-9KKPFYTP).

Each scenario runs in a child python with its own hard timeout, so a regression
cannot hang the suite that runs it. Survivors are checked by process-group id.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_REPRO = """
import os, signal, time, pytest

@pytest.mark.parametrize("i", range(20))
def test_sleep(i):
    if i == 0:
        open(os.environ["PGID_FILE"], "w").write(str(os.getpgid(0)))
    time.sleep(3)

def test_kill():
    time.sleep(1)
    os.kill(os.getpid(), signal.SIGKILL)
"""

# Runs the real helper from publish.py; exit 3 = helper timed out and killed the group.
_DRIVER = """
import subprocess, sys
sys.path.insert(0, {scripts!r})
import publish
from pathlib import Path
cmd = ["uv", "run", "--project", {root!r}, "--extra", "dev", "pytest", {test!r},
       "--rootdir", {tmp!r}, "-p", "no:cacheprovider", "-x", "-q", "-n", "4",
       "--dist", "loadgroup", "--timeout=300", "--timeout-method=thread"] + {extra!r}
try:
    sys.exit(publish.run_pytest_in_own_session(cmd, Path({tmp!r}), {timeout}))
except subprocess.TimeoutExpired:
    sys.exit(3)
"""


def _run_scenario(tmp_path: Path, extra: list[str], timeout: int) -> tuple[int, int]:
    """Run the crash scenario; return (driver exit code, pgid of the pytest run)."""
    test = tmp_path / "test_repro.py"
    test.write_text(_REPRO)
    pgid_file = tmp_path / "pgid"
    driver = textwrap.dedent(_DRIVER).format(
        scripts=str(ROOT / "scripts"), root=str(ROOT), test=str(test),
        tmp=str(tmp_path), extra=extra, timeout=timeout)
    p = subprocess.run([sys.executable, "-c", driver], timeout=240,
                       env={**os.environ, "PGID_FILE": str(pgid_file)},
                       capture_output=True, text=True)
    return p.returncode, int(pgid_file.read_text())


def _group_gone(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return True
    return False


def test_crash_fails_promptly_with_restart_limit(tmp_path: Path) -> None:
    """With the gate's real flags a killed worker ends the run non-zero, nothing survives."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import publish
    assert "--max-worker-restart=0" in publish._PYTEST_CMD
    code, pgid = _run_scenario(tmp_path, ["--max-worker-restart=0"], timeout=120)
    assert code not in (0, 3)
    assert _group_gone(pgid)


@pytest.mark.skipif(not hasattr(os, "killpg"), reason="needs POSIX process groups")
def test_hung_run_is_killed_as_a_group_on_timeout(tmp_path: Path) -> None:
    """Without the restart limit the run hangs; the timeout must kill every descendant."""
    code, pgid = _run_scenario(tmp_path, [], timeout=25)
    assert code == 3
    assert _group_gone(pgid)
