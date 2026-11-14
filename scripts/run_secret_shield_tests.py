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
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
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


def _run_in_own_session(cmd: list[str], cwd: Path, timeout: int) -> tuple[int, str]:
    """Run `cmd`; on timeout or interrupt kill its whole process group. Returns (exit code, output)."""
    # WHY a session of its own: `claude plugin test` runs each test file in a child of itself, and
    # killing only the direct child on timeout would orphan them. The group id equals the child pid,
    # so killpg reaches every descendant (same pattern as publish.run_pytest_in_own_session).
    proc = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", start_new_session=True)
    try:
        output, _ = proc.communicate(timeout=timeout)
    except BaseException:
        # BaseException: a Ctrl-C no longer reaches a child in another session.
        # WHY suppress: the group may already be gone (child exited just before the signal).
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        # WHY bounded: an unkillable (D-state) child must not hang the caller forever.
        proc.communicate(timeout=30)
        raise
    return proc.returncode, output


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
        return _fail("could not parse the pass/fail counts from the run's output", output)
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
