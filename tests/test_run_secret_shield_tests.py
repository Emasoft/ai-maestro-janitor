"""scripts/run_secret_shield_tests.py fails closed and passes only on a healthy shield (TRDD-3GP0D06D).

Real runs of the real script against the real `claude` binary; nothing is mocked. The tests that need
`claude` skip when it is not installed: CI has no `claude` install step yet (open owner decision on
the card), and without the skip the whole parallel suite would go red there. The publish gate does not
rely on these skips: it runs the script itself, which fails closed when `claude` is missing.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import pytest

_F = TypeVar("_F", bound=Callable[..., object])

_REPO = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO / "scripts" / "run_secret_shield_tests.py"
_MOD_DIR = _REPO / "hooks" / "secret-shield"

sys.path.insert(0, str(_REPO / "scripts"))

import run_secret_shield_tests as shield_runner  # noqa: E402

_skip_without_claude = pytest.mark.skipif(shutil.which("claude") is None, reason="`claude` is not installed here: `claude plugin test` is what runs the shield tests")


def needs_claude(test: _F) -> _F:
    # real_subprocess("claude"): the sandbox guard denies a real `claude` spawn by default; this suite
    # needs the real binary, since `claude plugin test` is the only runner of the shield tests.
    return _skip_without_claude(pytest.mark.real_subprocess("claude")(test))


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    # cwd=/tmp: never the repo root, as the script itself insists on.
    return subprocess.run([sys.executable, str(_SCRIPT), *args], cwd="/tmp", env=env, capture_output=True, text=True, timeout=400)


def _copy_mod(dest: Path) -> Path:
    shutil.copytree(_MOD_DIR, dest, ignore=shutil.ignore_patterns(".DS_Store"))
    return dest


def test_script_fails_closed_when_claude_is_not_on_path(tmp_path: Path) -> None:
    """With a PATH that holds no `claude`, the script exits 1 and says so."""
    result = _run(env={"PATH": str(tmp_path)})
    assert result.returncode == 1
    assert "`claude` is not on PATH" in result.stderr


@needs_claude
def test_a_deliberately_failing_shield_test_fails_the_script(tmp_path: Path) -> None:
    """A failing test(...) injected into a copy of the mod makes the script exit 1 (the card's Done-when)."""
    mod = _copy_mod(tmp_path / "secret-shield")
    with (mod / "tests" / "incident.test.ts").open("a", encoding="utf-8") as handle:
        handle.write("\ntest('deliberate failure injected by test_run_secret_shield_tests', () => {\n  expect(1).toBe(2)\n})\n")
    result = _run("--mod-dir", str(mod))
    assert result.returncode == 1
    assert "`claude plugin test` exited 1" in result.stderr
    assert "deliberate failure injected by test_run_secret_shield_tests" in result.stderr


@needs_claude
def test_the_liveness_mod_passes_through_the_script() -> None:
    """`--mod liveness` assembles hooks/liveness, runs its suite and exits 0 reporting its pass count (TRDD-KADV0ZO6)."""
    result = _run("--mod", "liveness")
    assert result.returncode == 0, result.stderr
    assert "OK: liveness: " in result.stdout


@needs_claude
def test_a_deliberately_failing_liveness_test_fails_the_script(tmp_path: Path) -> None:
    """A failing test(...) injected into a copy of hooks/liveness makes `--mod liveness` exit 1 (TRDD-KADV0ZO6)."""
    mod = tmp_path / "liveness"
    shutil.copytree(_REPO / "hooks" / "liveness", mod, ignore=shutil.ignore_patterns(".DS_Store"))
    with (mod / "tests" / "liveness.test.ts").open("a", encoding="utf-8") as handle:
        handle.write("\ntest('deliberate failure injected by test_run_secret_shield_tests', () => {\n  expect(1).toBe(2)\n})\n")
    result = _run("--mod", "liveness", "--mod-dir", str(mod))
    assert result.returncode == 1
    assert "`claude plugin test` exited 1" in result.stderr
    assert "deliberate failure injected by test_run_secret_shield_tests" in result.stderr


@needs_claude
def test_a_mod_dir_with_no_test_files_fails_the_script(tmp_path: Path) -> None:
    """A mod copy whose tests/ directory is gone exits 1 instead of passing on nothing."""
    mod = _copy_mod(tmp_path / "secret-shield")
    shutil.rmtree(mod / "tests")
    result = _run("--mod-dir", str(mod))
    assert result.returncode == 1
    assert "no *.test.ts or *.test.tsx" in result.stderr


@needs_claude
def test_a_run_that_exceeds_its_timeout_fails_the_script(tmp_path: Path) -> None:
    """With `--timeout 1` the run (about 5 s) is killed and the script exits 1 saying it timed out."""
    result = _run("--mod-dir", str(_copy_mod(tmp_path / "secret-shield")), "--timeout", "1")
    assert result.returncode == 1
    assert "timed out" in result.stderr


@needs_claude
def test_a_suite_shrunk_below_the_floor_fails_the_script(tmp_path: Path) -> None:
    """A mod copy keeping only its smallest test file passes the run but fails the count floor.

    Passing the per-file check here also shows the expected file list comes from the copy, not from a
    hardcoded list: every other file was removed, and none is reported missing.
    """
    mod = _copy_mod(tmp_path / "secret-shield")
    test_files = sorted((mod / "tests").glob("*.test.ts"), key=lambda f: f.stat().st_size)
    assert len(test_files) > 1
    for extra in test_files[1:]:
        extra.unlink()
    result = _run("--mod-dir", str(mod))
    assert result.returncode == 1
    assert "below the floor" in result.stderr


def test_a_test_file_with_no_header_in_the_output_is_reported_missing() -> None:
    """Only the expected files whose `<path>:` header line is absent from the run output are returned."""
    output = "hooks/secret-shield/tests/a.test.ts:\n(pass) x [0.1ms]\n\nhooks/secret-shield/tests/c.test.ts:\n(pass) y [0.1ms]\n"
    expected = ["hooks/secret-shield/tests/a.test.ts", "hooks/secret-shield/tests/b.test.ts", "hooks/secret-shield/tests/c.test.ts"]
    assert shield_runner._unreported_test_files(expected, output) == ["hooks/secret-shield/tests/b.test.ts"]
