"""The hook wrapper must fail OPEN when the plugin tree is missing (janitor#281).

THE INCIDENT THIS EXISTS FOR (measured 2026-08-20). `uv run --script --quiet <MISSING>`
exits **2**, and for a PreToolUse hook exit 2 is not "the command failed" — it is the
BLOCKING code that DENIES the tool call. Any other non-zero exit is merely logged.

A plugin update / `/reload-plugins --force` empties the ACTIVE version directory in place
while refetching. In that window every command in hooks.json points at a path that no
longer exists, so all six PreToolUse hooks exit 2 together and every Bash/Edit call in
every live session is denied until the refetch lands (~15 min of a stalled session). The
non-atomic refetch is upstream's; converting a transient absence into a lockout was ours.

These tests run the REAL wrapper with a REAL shell — the whole behaviour under test is an
exit code produced by a shell script, so there is nothing meaningful to mock.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.real_subprocess("sh", "uv", "python3", "git")

_ROOT = Path(__file__).resolve().parents[1]
_WRAPPER = _ROOT / "hooks" / "hook-run.sh"
_HOOKS_JSON = _ROOT / "hooks" / "hooks.json"

# Exit 2 is the ONLY blocking code. The tests below are all really about "is it 2 or not".
_BLOCKING = 2


def _run(*args: str) -> int:
    return subprocess.run(["sh", str(_WRAPPER), *args], capture_output=True,
                          text=True, timeout=60).returncode


def test_a_missing_hook_script_does_not_block_the_tool_call() -> None:
    """The core guarantee: script absent -> exit 0, so the tool call proceeds."""
    assert _run("/nonexistent/definitely/not/here.py") == 0


def test_a_missing_hook_script_is_not_the_blocking_code() -> None:
    """Stated separately from the line above because THIS is the property that matters:
    whatever the wrapper answers for an absent script, it must never be 2."""
    assert _run("/nonexistent/definitely/not/here.py") != _BLOCKING


def test_an_empty_argument_does_not_block() -> None:
    """A malformed invocation must also fail open — never deny on our own bug."""
    assert _run("") == 0


def test_a_present_hook_that_denies_still_denies(tmp_path: Path) -> None:
    """THE SAFETY HALF. A blanket `|| exit 0` would have fixed the lockout by breaking
    every guard; pre-bash-safety and the publish lock depend on exit 2 surviving `exec`."""
    denier = tmp_path / "denier.py"
    denier.write_text("import sys\nsys.exit(2)\n", encoding="utf-8")
    assert _run(str(denier)) == _BLOCKING


def test_a_present_hook_that_allows_returns_zero(tmp_path: Path) -> None:
    """The ordinary path is untouched by the guard."""
    ok = tmp_path / "ok.py"
    ok.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    assert _run(str(ok)) == 0


def test_a_missing_WRAPPER_is_also_non_blocking(tmp_path: Path) -> None:
    """The wrapper lives inside the directory that gets emptied, so it can vanish too — and
    the SHELL's answer for that is not portable.

    MEASURED 2026-08-20, and this test is why the hole was found: `sh <missing>` exits 127 on
    macOS but **2** on the Linux CI runner — the BLOCKING code. So the first version of this
    design fell into its own trap on Linux: during the very window it exists to protect, a
    vanished wrapper would have denied every tool call.

    The wrapper is therefore invoked DIRECTLY (`<wrapper> <script>`), not as an argument to
    `sh`. A missing EXECUTABLE is "command not found", which POSIX fixes at 127 on every
    shell — while `sh <missing FILE>` is the case shells disagree about. Same protection,
    no platform dependency.

    A `test -f … && sh …` guard also worked, and was rejected for a different reason: it puts
    shell operators into all 29 hook commands, which the publish security gate reports as 29
    CRITICAL command-injection findings (measured — it blocked the v3.3.23 release). A single
    direct invocation has no operators.
    """
    missing = tmp_path / "gone.sh"
    rc = subprocess.run(["sh", "-c", f'"{missing}" x'],
                        capture_output=True, text=True, timeout=60).returncode
    assert rc != _BLOCKING, "a vanished wrapper must never produce the blocking code"
    assert rc == 127, f"expected POSIX command-not-found, got {rc}"


def test_the_shipped_commands_carry_no_shell_operators() -> None:
    """No `&&`, `||` or `;` in a hook command.

    Two independent reasons, both measured: the publish security gate flags a shell compound
    as CRITICAL command injection (29 findings, one per command, blocking the release), and a
    compound is harder to reason about at exactly the moment — a half-present plugin dir —
    when the exit code has to be exactly right.
    """
    cmds = [h["command"]
            for entries in json.loads(_HOOKS_JSON.read_text(encoding="utf-8"))["hooks"].values()
            for e in entries for h in e.get("hooks", [])]
    bad = [c for c in cmds if any(op in c for op in ("&&", "||", ";"))]
    assert not bad, f"hook commands must be a single invocation, got operators in: {bad}"


def test_the_wrapper_ships_executable() -> None:
    """The direct-invocation form REQUIRES the exec bit — without it the shell reports
    'permission denied' (126), and while 126 is still non-blocking, every hook would silently
    stop running. Checked against git's recorded mode, not the working copy's, because that
    is what a cloner and the published package actually receive."""
    mode = subprocess.run(["git", "ls-files", "-s", "hooks/hook-run.sh"],
                          cwd=str(_ROOT), capture_output=True, text=True, timeout=60).stdout
    assert mode.startswith("100755"), f"hooks/hook-run.sh is not tracked as executable: {mode!r}"


def test_every_hooks_json_command_goes_through_the_wrapper() -> None:
    """A hook wired straight to `uv run` is a hole in exactly the window this closes, so the
    invariant is checked over the shipped config rather than trusted to review."""
    cmds = [h["command"]
            for entries in json.loads(_HOOKS_JSON.read_text(encoding="utf-8"))["hooks"].values()
            for e in entries for h in e.get("hooks", [])]
    assert cmds, "hooks.json declares no commands — the config is not being read correctly"
    unguarded = [c for c in cmds if "hooks/hook-run.sh " not in c]
    assert not unguarded, f"these hook commands bypass the fail-open wrapper: {unguarded}"


def test_the_wrapper_is_shipped_and_executable() -> None:
    """A hooks.json pointing at a wrapper the package does not ship would break every hook."""
    assert _WRAPPER.is_file(), "hooks/hook-run.sh is not shipped"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell semantics")
def test_wrapper_preserves_an_arbitrary_nonzero_exit(tmp_path: Path) -> None:
    """Non-2 failures must pass through unchanged: they are informative and non-blocking,
    and swallowing them would hide real hook crashes."""
    boom = tmp_path / "boom.py"
    boom.write_text("import sys\nsys.exit(7)\n", encoding="utf-8")
    assert _run(str(boom)) == 7
