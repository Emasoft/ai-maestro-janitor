"""Tests for publish.run_cpv_strict: a validator run that skipped a check must be detectable.

WHY (2026-10-07): the remote validator exited 0 while printing
`[WARNING] markdownlint timed out — skipping markdown lint`, so publish step 4 passed
a run that had not checked anything. Real child processes only, no mocks.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import publish  # noqa: E402

_L1 = "[WARNING] markdownlint timed out — skipping markdown lint"
_L2 = "[WARNING] pyright timed out after 180s — skipping type check"


def _py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_skip_lines_on_stdout_are_collected(tmp_path: Path) -> None:
    """Two skip lines printed on stdout with exit 0 are returned."""
    code = f"print({_L1!r}); print({_L2!r})"
    assert publish.run_cpv_strict(_py(code), tmp_path, timeout=60) == (0, [_L1, _L2])


def test_skip_lines_on_stderr_are_collected(tmp_path: Path) -> None:
    """The same lines on stderr are collected too."""
    code = f"import sys; print({_L1!r}, file=sys.stderr); print({_L2!r}, file=sys.stderr)"
    assert publish.run_cpv_strict(_py(code), tmp_path, timeout=60) == (0, [_L1, _L2])


def test_ordinary_warnings_are_not_skip_lines(tmp_path: Path) -> None:
    """A plain warning and an unrelated 'skipping' line are not skipped checks."""
    code = "print('[WARNING] something ordinary'); print('skipping bump')"
    assert publish.run_cpv_strict(_py(code), tmp_path, timeout=60) == (0, [])


def test_failure_exit_code_is_returned(tmp_path: Path) -> None:
    """A non-zero exit with no skip line returns that code and no lines."""
    assert publish.run_cpv_strict(_py("import sys; sys.exit(2)"), tmp_path, timeout=60) == (2, [])


def test_timeout_kills_the_whole_process_group(tmp_path: Path) -> None:
    """On timeout TimeoutExpired is raised and a sleeping grandchild is killed."""
    pidfile = tmp_path / "grandchild.pid"
    code = (
        "import subprocess, sys, time\n"
        "g = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
        f"open({str(pidfile)!r}, 'w').write(str(g.pid))\n"
        "time.sleep(120)\n"
    )
    start = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        publish.run_cpv_strict(_py(code), tmp_path, timeout=3)
    assert time.monotonic() - start < 40
    pid = int(pidfile.read_text())
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.2)
    os.kill(pid, 9)
    pytest.fail("the grandchild survived the timeout")


def test_only_run_cpv_strict_invokes_the_strict_validator() -> None:
    """Exactly two run_cpv_strict calls exist and no other call holds the strict list."""
    tree = ast.parse(Path(publish.__file__).read_text(encoding="utf-8"))
    helper_calls = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if name == "run_cpv_strict":
            helper_calls += 1
            continue
        if node.args and isinstance(node.args[0], ast.List):
            lits = [e.value for e in node.args[0].elts if isinstance(e, ast.Constant)]
            assert not ("cpv-remote-validate" in lits and "--strict" in lits), (
                f"line {node.lineno} runs the strict validator without run_cpv_strict"
            )
    assert helper_calls == 2



def test_unfinished_reader_fails_closed(tmp_path: Path) -> None:
    """A detached grandchild holding stdout open makes the result unprovable, not clean."""
    # The grandchild sleeps 30 s and exits by itself: the sandbox guard forbids signalling
    # a process this test did not spawn directly.
    code = (
        "import subprocess, sys\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],"
        " start_new_session=True)\n"
    )
    start = time.monotonic()
    rc, lines = publish.run_cpv_strict(_py(code), tmp_path, timeout=60)
    assert rc == 0
    assert len(lines) == 1 and "cannot prove" in lines[0]
    assert time.monotonic() - start < 25


def _fake_uvx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lines: list[str], rc: int) -> None:
    """Put an executable `uvx` that prints `lines` and exits `rc` first on PATH."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "uvx"
    body = "".join(f"print({ln!r})\n" for ln in lines)
    script.write_text(f"#!{sys.executable}\nimport sys\n{body}sys.exit({rc})\n", encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")


def test_skipped_check_with_exit_0_blocks_both_sites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Skip lines with exit 0 stop step 4 with code 1 and make the push gate return 1."""
    _fake_uvx(tmp_path, monkeypatch, [_L1, _L2], 0)
    with pytest.raises(SystemExit) as exc:
        publish.stage_validate(tmp_path)
    assert exc.value.code == 1
    assert publish._gate_validate(tmp_path) == 1


def test_ordinary_warning_passes_both_sites(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An ordinary warning with exit 0 passes step 4 and the push gate."""
    _fake_uvx(tmp_path, monkeypatch, ["[WARNING] something ordinary"], 0)
    assert publish.stage_validate(tmp_path) is None
    assert publish._gate_validate(tmp_path) == 0


def test_skipped_check_with_warning_exit_5_still_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Skip lines with exit 5 block the push gate; step 4 stops with code 5."""
    _fake_uvx(tmp_path, monkeypatch, [_L1, _L2], 5)
    assert publish._gate_validate(tmp_path) == 1
    with pytest.raises(SystemExit) as exc:
        publish.stage_validate(tmp_path)
    assert exc.value.code == 5


def test_blocking_exit_4_blocks_both_sites(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exit 4 with no skip line blocks the push gate and stops step 4 with code 4."""
    _fake_uvx(tmp_path, monkeypatch, [], 4)
    assert publish._gate_validate(tmp_path) == 1
    with pytest.raises(SystemExit) as exc:
        publish.stage_validate(tmp_path)
    assert exc.value.code == 4
