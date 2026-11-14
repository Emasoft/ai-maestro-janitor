#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""run_secret_shield_tests — run a hooks/ mod's tests (secret-shield by default, or liveness with
`--mod liveness`) through `claude plugin test` (TRDD-3GP0D06D, TRDD-KADV0ZO6).

WHY THIS EXISTS. hooks/<mod>/tests are run by the mods test kit (`claude-code/testing`),
which only the `claude` binary provides. Nothing in publish.py or CI ran them, so a release could
ship a mod that fails its own tests. The script keeps its secret-shield name: it was written for that
mod, and publish.py and the tests name it.

HOW. `claude plugin test <dir>` refuses a bare mod directory ("no hooks module to load; there is no
hooks/hooks.json naming one in "modules""), and a minimal plugin.json fails two userConfig tests. So
the mod is assembled in a fresh temp dir: the repo's full .claude-plugin/plugin.json, a
hooks/hooks.json holding ONLY {"modules": ["./<mod>/register.ts"]}, and a copy of the mod.
The repo's own hooks/hooks.json is never read or written: it must not carry a "modules" key until
the wiring gate (tests/test_secret_shield_wiring_gate.py) allows it. The run is pointed at the temp
dir, never at the repo root: _corpus_dev/ holds untrusted *.test.ts that a root discovery would run.

Exit 0: the run passed, reported at least the mod's floor of passing tests, and every test file of the copy appeared in its output. Exit 1: anything else, with
one `run_secret_shield_tests: FAIL:` line on stderr (the run's own output follows when it ran).
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_PLUGIN_JSON = _REPO / ".claude-plugin" / "plugin.json"
_DEFAULT_MOD = "secret-shield"
_DEFAULT_TIMEOUT_SEC = 300

# Floor of passing tests per mod, measured 2026-11-14: secret-shield 841 passing across 4 files (suite
# wall time ~5 s), liveness 15 passing in 1 file (~0.3 s). WHY a floor at all:
# `claude plugin test` exits 1 when it finds NO test file (measured), so an empty assembly is already
# caught, and the per-file check catches a file of the assembly that the run did not execute. What
# neither sees is a test file REMOVED from the repo (the assembly is built from what is left) or tests
# silently not collected inside a file: both still exit 0 with fewer passes. secret-shield 800 catches a
# large loss (~40+ tests); a single small file removed from the repo can still pass. liveness 15 is its
# exact count (one file, so any removed or uncollected test is caught); a removed liveness test must
# lower it in the same commit. Lower a floor in the same commit that removes tests, never to make a red
# run green.
_MIN_PASSED = {"secret-shield": 800, "liveness": 15}

_PASS_RE = re.compile(r"^\s*(\d+) pass\s*$", re.MULTILINE)
_FAIL_RE = re.compile(r"^\s*(\d+) fail\s*$", re.MULTILINE)


def _fail(message: str, output: str = "") -> int:
    print(f"run_secret_shield_tests: FAIL: {message}", file=sys.stderr)
    if output:
        print(output, file=sys.stderr)
    return 1


def _unreported_test_files(expected: list[str], output: str) -> list[str]:
    """Return the expected test files (paths relative to the assembly root) with no `<path>:` header line in `output`."""
    return [rel for rel in expected if re.search(rf"^{re.escape(rel)}:\s*$", output, re.MULTILINE) is None]


def _output_summary(output: str, tail_lines: int = 20) -> str:
    """Byte length, line count and last `tail_lines` lines of `output`, for a run whose output cannot be parsed."""
    # WHY (TRDD-LAUPB305): on 2026-11-14 a run exited 0 with output cut mid-line and no count lines. `_fail` prints
    # the whole output, ~500 lines, so where it stopped is buried; the length, line count and tail printed first
    # show at once whether the output was cut and where. Bytes are of the decoded text re-encoded as UTF-8, because
    # the run is read with errors="replace".
    lines = output.splitlines()
    tail = "\n".join(lines[-tail_lines:])  # splitlines: no phantom empty last line when the output ends with a newline
    return f"output: {len(output.encode('utf-8'))} bytes, {output.count(chr(10))} newlines, ends with a newline: {output.endswith(chr(10))}; last {min(tail_lines, len(lines))} lines:\n{tail}\n--- full output follows ---"

_GROUP_POLL_SEC = 0.05


@dataclass(frozen=True)
class CapturedRun:
    """Outcome of run_captured_in_own_session. `returncode` is the direct child's exit code: negative if the child itself was killed, but when the timeout or abort fires after the child already exited (the group-wait phase) it is the child's real exit code, often 0. Callers must check `timed_out`/`aborted` first."""

    returncode: int
    output: str
    timed_out: bool
    aborted: bool


def _group_alive(pgid: int) -> bool:
    # PermissionError counts as gone, like ProcessLookupError: killpg(pgid, 0) raises EPERM when it may signal no member of the group:
    # either only zombies remain (inferred for macOS, not measured here) or only members owned by another user remain. Both are
    # treated as gone; for the second case that would end the wait while an other-uid descendant could still write, accepted
    # because `claude plugin test` starts no setuid descendants.
    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def run_captured_in_own_session(cmd: list[str], cwd: Path, timeout: float, should_abort: Callable[[], bool] | None = None, poll_s: float = 0.5) -> CapturedRun:
    """Run `cmd` in a session of its own with stdout+stderr captured in a REGULAR FILE; kill the whole group on timeout, abort or interrupt."""
    # WHY a regular file and never a pipe (TRDD-LAUPB305, measured 2026-11-14): `claude plugin test` is bun-based and writes a
    # regular file synchronously but a pipe asynchronously, and it exits with its pipe writes still pending, so everything past
    # the pipe capacity (~64 KiB) is lost with exit code 0. That is an upstream defect of claude, not a reader bug: 5 of 320
    # pipe-captured runs were cut, every one 65500 bytes into the 116 KB patterns.test.ts block (offset 77931 = 12431 + 65500),
    # ending mid-line; 0 of 180 file-captured runs were cut. A node/bun script doing one 200 KB write then process.exit(0) loses
    # its tail through a pipe in 50 of 50 runs and never through a regular file. A regular file is the capture such a producer
    # writes completely, so there is no pipe fallback.
    # WHY the output is read only once no process is left in the child's group: a child of claude (a per-test-file runner)
    # may still write to the inherited fd after claude itself has exited, so the child's exit is not the end of the output.
    # The group id equals the child pid (start_new_session). A descendant that moves to another process group would escape this
    # wait (unlikely for `claude plugin test`). The only bound is `timeout`; reaching it is the timeout failure path. A descendant
    # that stays in the group after letting go of the output fd (e.g. a leaked background process) now makes the run end as a
    # timeout, where the old pipe reader would have returned (a descendant that keeps the fd blocked both readers alike). After
    # proc.wait reaps the child its pid is free: if the group empties and an unrelated session leader reuses that pid within one
    # poll, the wait and the timeout kill would target that unrelated group; accepted as a narrow race (pid reuse inside 50 ms),
    # not guarded.
    # WHY a session of its own: killing only the direct child on timeout would orphan its descendants (same pattern as publish.run_pytest_in_own_session).
    deadline = time.monotonic() + timeout
    timed_out = aborted = False

    def interrupted() -> bool:
        nonlocal timed_out, aborted
        aborted = should_abort is not None and should_abort()
        timed_out = not aborted and time.monotonic() > deadline
        return aborted or timed_out

    def kill_group(pgid: int) -> None:
        # WHY suppress both: the group may already be gone (child exited just before the signal), or killpg may raise EPERM: the group
        # holds only zombies (macOS, inferred) or only members of another uid, which then survive the kill unreported. An unsuppressed
        # EPERM in the except-BaseException path would replace the original exception and skip proc.wait.
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pgid, signal.SIGKILL)

    with tempfile.TemporaryFile() as capture:
        proc = subprocess.Popen(cmd, cwd=str(cwd), stdout=capture, stderr=subprocess.STDOUT, start_new_session=True)
        pgid = proc.pid
        try:
            while True:
                try:
                    proc.wait(timeout=poll_s)
                    break
                except subprocess.TimeoutExpired:
                    if interrupted():
                        break
            while not (aborted or timed_out) and _group_alive(pgid):
                if interrupted():
                    break
                time.sleep(_GROUP_POLL_SEC)
            if aborted or timed_out:
                kill_group(pgid)
        except BaseException:
            # BaseException: a Ctrl-C no longer reaches a child in another session.
            kill_group(pgid)
            # WHY bounded: an unkillable (D-state) child must not hang the caller forever.
            proc.wait(timeout=30)
            raise
        # WHY bounded: an unkillable (D-state) child must not hang the caller forever.
        proc.wait(timeout=30)
        capture.seek(0)
        # Text mode with errors="replace" and universal newlines, what `text=True, errors="replace"` gave the pipe readers.
        reader = io.TextIOWrapper(capture, encoding="utf-8", errors="replace", newline=None)
        output = reader.read()
        reader.detach()
    return CapturedRun(proc.returncode, output, timed_out, aborted)


def _run_in_own_session(cmd: list[str], cwd: Path, timeout: int) -> tuple[int, str]:
    """Run `cmd`; on timeout or interrupt kill its whole process group. Returns (exit code, output)."""
    result = run_captured_in_own_session(cmd, cwd, timeout)
    if result.timed_out:
        raise subprocess.TimeoutExpired(cmd, timeout)
    return result.returncode, result.output


def assemble_plugin_dir(tmp: Path, mod: str, mod_dir: Path) -> list[str]:
    """Assemble the temp plugin dir for `claude plugin test` in `tmp`; return the expected test files (paths relative to `tmp`)."""
    # WHY a function: the load harness planned in TRDD-OD5Z90YL (D8) reuses it, so the harness and the
    # release gate assemble the plugin identically.
    (tmp / ".claude-plugin").mkdir()
    shutil.copy2(_PLUGIN_JSON, tmp / ".claude-plugin" / "plugin.json")
    (tmp / "hooks").mkdir()
    (tmp / "hooks" / "hooks.json").write_text(f'{{"modules": ["./{mod}/register.ts"]}}\n', encoding="utf-8")
    shutil.copytree(mod_dir, tmp / "hooks" / mod, ignore=shutil.ignore_patterns(".DS_Store"))
    # WHY computed from the copy, never a hardcoded list: a renamed or added test file is checked
    # automatically, and a stale list would fail on the first rename.
    # WHY hooks/<mod>/tests/load/*.load.ts are deliberately uncollected: `claude plugin test` runs only *.test.ts and *.test.tsx, so the ReDoS load probe stays out of the gate's count; the load harness (tests/harness/redos_load_harness.py, TRDD-OD5Z90YL) copies probe.load.ts to probe.test.ts in its own assembly.
    tests_dir = tmp / "hooks" / mod / "tests"
    return sorted(f.relative_to(tmp).as_posix() for pattern in ("*.test.ts", "*.test.tsx") for f in tests_dir.rglob(pattern))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run a hooks/ mod's tests via `claude plugin test` in a temp assembly.")
    parser.add_argument("--mod", choices=sorted(_MIN_PASSED), default=_DEFAULT_MOD, help=f"which hooks/<mod> to test (default {_DEFAULT_MOD})")
    parser.add_argument("--mod-dir", type=Path, default=None, help="directory assembled as hooks/<mod> (default: the repo's hooks/<mod>)")
    parser.add_argument("--timeout", type=int, default=_DEFAULT_TIMEOUT_SEC, help="seconds before the run's process group is killed (default 300)")
    args = parser.parse_args(argv)
    mod: str = args.mod
    mod_dir: Path = args.mod_dir if args.mod_dir is not None else _REPO / "hooks" / mod
    min_passed = _MIN_PASSED[mod]

    # WHY fail closed on a missing binary: the tests cannot run without it, and "skipped" would let a
    # release ship an untested mod — exactly the gap this script closes.
    claude = shutil.which("claude")
    if claude is None:
        return _fail(f"`claude` is not on PATH; the {mod} tests need its mods test kit")
    if not mod_dir.is_dir():
        return _fail(f"mod dir not found: {mod_dir}")
    if not _PLUGIN_JSON.is_file():
        return _fail(f"manifest not found: {_PLUGIN_JSON}")

    with tempfile.TemporaryDirectory(prefix=f"{mod}-tests-") as tmp_name:
        tmp = Path(tmp_name)
        expected = assemble_plugin_dir(tmp, mod, mod_dir)
        try:
            code, output = _run_in_own_session([claude, "plugin", "test", str(tmp)], tmp, args.timeout)
        except subprocess.TimeoutExpired:
            # WHY: a hung run asserts nothing; reporting it as a pass or a skip would hide a wedged mod.
            return _fail(f"`claude plugin test` timed out after {args.timeout}s; its process group was killed")

    if code != 0:
        # WHY: the runner's own verdict (a failed test, or no hooks module / no test file) is final.
        return _fail(f"`claude plugin test` exited {code}", output)
    passed = _PASS_RE.findall(output)
    failed = _FAIL_RE.findall(output)
    if not passed or not failed:
        # WHY: an exit 0 with no count line means the output format changed or the run did not
        # report; the floor below could not be checked, so the run proves nothing.
        # WHY the summary (TRDD-LAUPB305): the full output alone buried where a cut-off run stopped; never loosen this check to make a cut-off run pass.
        return _fail(f"could not parse the pass/fail counts from the run's output\n{_output_summary(output)}", output)
    n_pass, n_fail = int(passed[-1]), int(failed[-1])
    if n_fail != 0:
        # WHY: the exit code and the counts must agree; a disagreement is not a pass.
        return _fail(f"exit 0 but the run reports {n_fail} failing test(s)", output)
    # WHY per file: `claude plugin test` prints a `<path>:` header line for every test file it ran
    # (measured, claude 2026-11-14). A file present in the assembly but absent from the output was not
    # run, which the total count alone can hide while it stays above the floor.
    unreported = _unreported_test_files(expected, output)
    if unreported:
        return _fail(f"test file(s) in the assembly are missing from the run's output: {', '.join(unreported)}", output)
    if n_pass < min_passed:
        return _fail(f"only {n_pass} tests passed, below the floor of {min_passed}: part of the suite was not collected", output)
    print(f"run_secret_shield_tests: OK: {mod}: {n_pass} pass, {n_fail} fail (floor {min_passed})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
