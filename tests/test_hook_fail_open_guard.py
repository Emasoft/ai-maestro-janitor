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

pytestmark = pytest.mark.real_subprocess("sh", "uv", "python3")

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

    The command shape is therefore `test -f <wrapper> && sh <wrapper> <script>`. POSIX fixes
    `test` at exit 1 for false, on every shell and platform, and 1 is non-blocking — so this
    no longer depends on how a particular shell reports an unopenable file.
    """
    missing = tmp_path / "gone.sh"
    rc = subprocess.run(
        ["sh", "-c", f'test -f "{missing}" && sh "{missing}" x'],
        capture_output=True, text=True, timeout=60,
    ).returncode
    assert rc != _BLOCKING, "a vanished wrapper must never produce the blocking code"


def test_the_shipped_command_shape_guards_the_wrapper_itself() -> None:
    """hooks.json must use the `test -f … && sh …` form, not a bare `sh <wrapper>`.

    Pinned in the CONFIG, because the platform difference above is invisible on the
    maintainer's machine: a bare `sh` form passes every local test and only fails on Linux,
    which is exactly how it shipped in v3.3.22 and reddened CI.
    """
    cmds = [h["command"]
            for entries in json.loads(_HOOKS_JSON.read_text(encoding="utf-8"))["hooks"].values()
            for e in entries for h in e.get("hooks", [])]
    bare = [c for c in cmds if not c.startswith("test -f ")]
    assert not bare, f"these commands do not guard the wrapper's own existence: {bare}"


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
