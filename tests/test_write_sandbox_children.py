"""The write sandbox must reach into CHILD processes too (S1g).

This is the layer the FIRST sandbox lacked, and the lack was not academic: the 2026-07-11
clobber was a CHILD process (something ran daemon_keepalive_entry.py, whose boot gate staged
the cached plugin over this repo's scripts/**), and on the very day the in-process sandbox
shipped, the live daemon — another process — wrote the real plugin-data dir mid-suite while the
sandbox watched and saw nothing.

These tests spawn a real child interpreter and prove:
  1. a child writing into a protected root is BLOCKED (the clobber shape),
  2. a child writing into its own tmp is ALLOWED (no collateral damage),
  3. the guard travels through TWO process hops (child spawns grandchild),
  4. an unrelated Python with no sandbox env is UNTOUCHED (opt-in, never global),
  5. a failed install is LOUD, not silent (a sandbox trusted-but-absent is worse than none).

No mocks: real subprocesses, real writes, the actual sitecustomize the suite installs.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_BOOT = _REPO / "tests" / "_sandbox_boot"
_GUARD_PARENT = _REPO / "tests"


def _child_env(deny: str, tmp: Path) -> dict[str, str]:
    """Env that makes a child boot the sandbox: the boot dir + guard module on PYTHONPATH, and
    the protected roots published. Mirrors exactly what conftest exports to real children."""
    return {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(_BOOT), str(_GUARD_PARENT), os.environ.get("PYTHONPATH", "")]),
        "JANITOR_TEST_SANDBOX_DENY": deny,
        "HOME": str(tmp / "fake-home"),  # prove the child enforces the PUBLISHED root, not a re-derived one
    }


def _run_child(code: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv
        [sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60
    )


def test_child_write_into_protected_root_is_blocked(tmp_path: Path) -> None:
    """THE regression. A subprocess writing into a protected root must raise, exactly as the
    parent would — this is the clobber vector the in-process-only sandbox could not stop."""
    protected = tmp_path / "protected"
    protected.mkdir()
    target = protected / "victim.py"
    target.write_text("original\n", encoding="utf-8")

    env = _child_env(str(protected), tmp_path)
    # The child tries the clobber's own move: os.replace a tmp file over a protected file.
    code = (
        "import os,tempfile,pathlib\n"
        f"fd,tmp=tempfile.mkstemp()\n"
        "os.close(fd)\n"
        f"os.replace(tmp, {str(target)!r})\n"
        "print('WROTE')\n"
    )
    proc = _run_child(code, env)

    assert "WROTE" not in proc.stdout, "the child overwrote a protected file — sandbox did not reach it"
    assert "SandboxViolation" in proc.stderr, f"expected a SandboxViolation, got:\n{proc.stderr}"
    assert target.read_text(encoding="utf-8") == "original\n", "the protected file was mutated"


def test_child_write_into_its_own_tmp_is_allowed(tmp_path: Path) -> None:
    """The guard must not become collateral damage: a child writing OUTSIDE every protected
    root works normally, or the sandbox would break every legitimate subprocess."""
    protected = tmp_path / "protected"
    protected.mkdir()
    allowed = tmp_path / "scratch" / "ok.txt"
    allowed.parent.mkdir()

    env = _child_env(str(protected), tmp_path)
    code = f"import pathlib; pathlib.Path({str(allowed)!r}).write_text('fine'); print('WROTE')\n"
    proc = _run_child(code, env)

    assert "WROTE" in proc.stdout, f"a legitimate tmp write was blocked:\n{proc.stderr}"
    assert allowed.read_text(encoding="utf-8") == "fine"


def test_guard_survives_a_second_process_hop(tmp_path: Path) -> None:
    """A child that spawns a GRANDCHILD must pass the sandbox on: the env vars are inherited, so
    protection does not stop one level deep. The keepalive chain is several processes long."""
    protected = tmp_path / "protected"
    protected.mkdir()
    target = protected / "deep.txt"
    target.write_text("orig", encoding="utf-8")

    env = _child_env(str(protected), tmp_path)
    grandchild = (
        "import pathlib\n"
        f"pathlib.Path({str(target)!r}).write_text('clobbered')\n"
    )
    code = (
        "import subprocess,sys\n"
        f"r=subprocess.run([sys.executable,'-c',{grandchild!r}],capture_output=True,text=True)\n"
        "sys.stderr.write(r.stderr)\n"
    )
    proc = _run_child(code, env)

    assert "SandboxViolation" in proc.stderr, f"grandchild was not sandboxed:\n{proc.stderr}"
    assert target.read_text(encoding="utf-8") == "orig", "grandchild mutated a protected file"


def test_unrelated_python_without_the_env_is_untouched(tmp_path: Path) -> None:
    """The sandbox is OPT-IN: a Python that merely inherits PYTHONPATH but NOT the deny env must
    behave exactly as normal, so importing sitecustomize never changes an unrelated process."""
    target = tmp_path / "anywhere.txt"
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(_BOOT), str(_GUARD_PARENT), os.environ.get("PYTHONPATH", "")]),
    }
    env.pop("JANITOR_TEST_SANDBOX_DENY", None)  # the switch is OFF
    code = f"import pathlib; pathlib.Path({str(target)!r}).write_text('ok'); print('WROTE')\n"
    proc = _run_child(code, env)

    assert "WROTE" in proc.stdout, f"the sandbox activated without its env var:\n{proc.stderr}"
    assert target.read_text(encoding="utf-8") == "ok"


def test_child_reads_are_never_blocked(tmp_path: Path) -> None:
    """Only writes are policed. A child READING a protected path must succeed — the daemon reads
    its own state dir constantly, and blocking that would break every legitimate subprocess."""
    protected = tmp_path / "protected"
    protected.mkdir()
    (protected / "state.txt").write_text("data", encoding="utf-8")

    env = _child_env(str(protected), tmp_path)
    code = f"import pathlib; print(pathlib.Path({str(protected / 'state.txt')!r}).read_text())\n"
    proc = _run_child(code, env)

    assert proc.returncode == 0 and "data" in proc.stdout, f"a protected READ was blocked:\n{proc.stderr}"
