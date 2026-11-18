"""scripts/run_secret_shield_tests.py fails closed and passes only on a healthy shield (TRDD-3GP0D06D).

Real runs of the real script against the real `claude` binary; nothing is mocked. The tests that need
`claude` skip when it is not installed: CI has no `claude` install step yet (open owner decision on
the card), and without the skip the whole parallel suite would go red there. The publish gate does not
rely on these skips: it runs the script itself, which fails closed when `claude` is missing.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
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
    # cwd is the temp dir, not the repo root: it keeps the child process out of the repo.
    # The script itself does not check its own cwd.
    return subprocess.run([sys.executable, str(_SCRIPT), *args], cwd=tempfile.gettempdir(), env=env, capture_output=True, text=True, timeout=400)


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



def test_the_output_summary_gives_bytes_newlines_and_the_last_twenty_lines_of_a_cut_off_run() -> None:
    """For a 30-line output cut mid-line, the summary reports its byte length, newline count, no final newline, and exactly the last 20 lines (TRDD-LAUPB305)."""
    lines = [f"(pass) test number {n} [0.1ms]" for n in range(29)] + ["(pass) the GitLab session cookie is hidden whole, the cookie name is kept > stays vis"]
    output = "\n".join(lines)
    summary = shield_runner._output_summary(output)
    assert f"{len(output.encode())} bytes, 29 newlines, ends with a newline: False; last 20 lines:" in summary
    assert "\n".join(lines[-20:]) in summary
    assert "test number 9 " not in summary
    assert "test number 10 " in summary


def test_the_output_summary_of_a_short_output_reports_its_real_line_count() -> None:
    """An output shorter than 20 lines reports its own line count (2 for "a", "b"), not 20, and still ends with the full-output marker."""
    summary = shield_runner._output_summary("a\nb\n")
    assert "last 2 lines:" in summary
    assert summary.endswith("--- full output follows ---")



_BIG_WRITE_BYTES = 200_000
# One 200 KB write, then process.exit(0): the shape of claude's exit with pipe writes pending (TRDD-LAUPB305).
_BIG_WRITE_JS = f'process.stdout.write("x".repeat({_BIG_WRITE_BYTES - 1}) + "\\n"); process.exit(0);'


def _js_runtime() -> str:
    runtime = shutil.which("node") or shutil.which("bun")
    if runtime is None:
        pytest.skip("neither node nor bun is on PATH: the exit-with-pending-write micro-test needs a JS runtime")
    return runtime


@pytest.mark.real_subprocess("node", "bun")
def test_the_file_capture_keeps_all_of_a_big_write_followed_by_process_exit(tmp_path: Path) -> None:
    """run_captured_in_own_session returns all 200000 bytes of a JS script that writes them in one call and then calls process.exit(0)."""
    script = tmp_path / "big_write.js"
    script.write_text(_BIG_WRITE_JS, encoding="utf-8")
    result = shield_runner.run_captured_in_own_session([_js_runtime(), str(script)], tmp_path, 60)
    assert result.returncode == 0
    assert not result.timed_out
    assert not result.aborted
    assert len(result.output) == _BIG_WRITE_BYTES


@pytest.mark.real_subprocess("node", "bun")
def test_a_plain_pipe_loses_the_tail_of_the_same_big_write(tmp_path: Path) -> None:
    """Documents the upstream claude/bun pipe defect; NOT a regression test of this code: it can only pass, skip, or error on a broken JS runtime, because its assertion cannot fail once the skip condition is false (a plain pipe read of the same script returns fewer than 200000 bytes; if this host returns them all in every run, it skips)."""
    script = tmp_path / "big_write.js"
    script.write_text(_BIG_WRITE_JS, encoding="utf-8")
    runtime = _js_runtime()
    # A few runs: the loss measured here is 50 of 50, but a pipe race must not turn into a red test.
    lengths = [len(subprocess.run([runtime, str(script)], capture_output=True, check=True, timeout=60).stdout) for _ in range(5)]
    if min(lengths) == _BIG_WRITE_BYTES and max(lengths) == _BIG_WRITE_BYTES:
        pytest.skip("the pipe returned the full 200000 bytes on this host in every run: the pipe loss did not reproduce here")
    assert min(lengths) < _BIG_WRITE_BYTES


@pytest.mark.real_subprocess("sh", "sleep")
def test_the_file_capture_waits_for_a_grandchild_that_writes_after_its_parent_exited(tmp_path: Path) -> None:
    """A background child still writing 1 s after the direct child exited is captured: the output is read only once the process group is empty."""
    result = shield_runner.run_captured_in_own_session(["sh", "-c", "echo first; (sleep 1; echo late) & exit 0"], tmp_path, 60)
    assert result.returncode == 0
    assert result.output == "first\nlate\n"


@pytest.mark.real_subprocess("sleep")
def test_the_file_capture_reports_a_timeout_and_kills_the_group(tmp_path: Path) -> None:
    """A command that outlives the timeout is killed with its group and reported as timed_out."""
    result = shield_runner.run_captured_in_own_session(["sleep", "30"], tmp_path, 0.3, poll_s=0.1)
    assert result.timed_out
    assert not result.aborted
    assert result.returncode < 0


@pytest.mark.real_subprocess("sh", "sleep")
def test_a_timeout_in_the_group_wait_phase_reports_the_childs_real_exit_code(tmp_path: Path) -> None:
    """When the direct child exits 0 but a grandchild keeps the group alive past the timeout, the run reports timed_out with returncode 0 (callers must check timed_out first) and the group kill reaps the grandchild."""
    pidfile = tmp_path / "grandchild.pid"
    result = shield_runner.run_captured_in_own_session(["sh", "-c", 'sleep 30 & echo "$$ $!" > "$1"; exit 0', "sh", str(pidfile)], tmp_path, 1.0, poll_s=0.1)
    assert result.timed_out
    assert not result.aborted
    assert result.returncode == 0
    group_leader, grandchild = (int(part) for part in pidfile.read_text().split())
    gone = False
    try:
        # WHY a poll: SIGKILL is delivered at once, but the killed grandchild stays visible to os.kill(pid, 0) as a zombie until launchd reaps it (it was orphaned when the sh child exited).
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            try:
                os.kill(grandchild, 0)
            except ProcessLookupError:
                gone = True
                break
            time.sleep(0.05)
    finally:
        if not gone:
            # WHY killpg on the sh leader and not os.kill on the grandchild: the sandbox guard only lets a test signal a process it spawned, and the orphaned grandchild is neither; the leader pid is the group id (start_new_session) and was spawned by the run.
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(group_leader, signal.SIGKILL)
    assert gone, f"grandchild {grandchild} survived the group kill in the group-wait phase"
