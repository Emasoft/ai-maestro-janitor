"""The pre-push hook must not run the release gate under a sub-3.11 interpreter.

TRDD-CN62E66F. `run_release_gate` prefers `uv run` (which honours pyproject's
`requires-python`) and falls back to a bare `python3` when uv is absent — the
least-controlled environment, and the one where the floor is least likely to hold.
`publish.py` imports `typing.assert_never` at module scope (3.11+), so a sub-3.11
interpreter dies with `ImportError: cannot import name 'assert_never'`: a diagnostic
naming a typing symbol, which tells the operator nothing about why their push was
blocked. The gate also runs on ordinary ref DELETIONS, so that message would surface
on routine cleanup unrelated to releasing.

These tests use a FAKE `python3` on PATH rather than a real old interpreter, because
the box requires covering the below-floor path on a machine that has only one Python.
The shim is the honest substitute: the hook's guard is a `python3 -c` subprocess, so
what it actually depends on is that command's exit status, and a shim controls exactly
that.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "git-hooks" / "pre-push"

# The guard's own predicate, copied from the hook. Kept in sync by
# test_the_guard_predicate_in_this_file_matches_the_hook below — a copy that can
# drift silently would make every other test here meaningless.
_PREDICATE = "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"


def _fake_python3(tmp_path: Path, *, version: tuple[int, int]) -> Path:
    """A directory containing a `python3` that reports `version` and nothing else."""
    d = tmp_path / "fakebin"
    d.mkdir(exist_ok=True)
    shim = d / "python3"
    shim.write_text(
        "#!/bin/sh\n"
        # Only the `-c <predicate>` form is used by the guard; anything else is a
        # test bug, so make it loud rather than silently passing.
        'if [ "$1" != "-c" ]; then echo "fake python3: unexpected argv: $*" >&2; exit 99; fi\n'
        f"exit {0 if version >= (3, 11) else 1}\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)
    return d


def _run_guard(python3_dir: Path) -> int:
    """Run the hook's version predicate with `python3_dir` first on PATH."""
    env = dict(os.environ, PATH=f"{python3_dir}{os.pathsep}{os.environ['PATH']}")
    return subprocess.run(
        ["python3", "-c", _PREDICATE],
        env=env, capture_output=True, text=True, timeout=30, check=False,
    ).returncode


def test_the_guard_predicate_in_this_file_matches_the_hook() -> None:
    """The copied predicate must be the hook's — a drifted copy would void every test below."""
    assert _PREDICATE in HOOK.read_text(encoding="utf-8")


def test_a_below_floor_python3_fails_the_guard(tmp_path: Path) -> None:
    """A 3.10 interpreter must FAIL the guard, so the gate is never invoked under it."""
    assert _run_guard(_fake_python3(tmp_path, version=(3, 10))) == 1


def test_an_at_floor_python3_passes_the_guard(tmp_path: Path) -> None:
    """Exactly 3.11 is the floor and must PASS — a guard that refuses everything is not a guard."""
    assert _run_guard(_fake_python3(tmp_path, version=(3, 11))) == 0


def test_an_above_floor_python3_passes_the_guard(tmp_path: Path) -> None:
    """A newer interpreter must pass too."""
    assert _run_guard(_fake_python3(tmp_path, version=(3, 13))) == 0


def test_the_guard_runs_before_publish_py_is_invoked() -> None:
    """Ordering is the whole point: a guard after the invocation would not prevent the ImportError."""
    text = HOOK.read_text(encoding="utf-8")
    guard_at = text.index(_PREDICATE)
    # The fallback's actual invocation, i.e. the bare-python3 one, not the uv branch.
    invoke_at = text.index("python3 scripts/publish.py --gate")
    assert guard_at < invoke_at, "the version guard must precede the bare-python3 invocation"


def test_the_uv_branch_returns_rather_than_falling_through() -> None:
    """`uv run` must not fall through into the fallback, or a uv host would run the gate twice."""
    text = HOOK.read_text(encoding="utf-8")
    uv_at = text.index("uv run python scripts/publish.py --gate")
    tail = text[uv_at:]
    assert tail.lstrip().splitlines()[1].strip() == "return $?"


def test_absent_python3_gets_its_own_message_not_the_too_old_one() -> None:
    """ABSENT and TOO-OLD are different failures: `python3 -c` exits 127 when there is no python3.

    Without a separate branch, `!` folds 127 into the same arm as a 3.10 interpreter and the
    operator is told theirs is "older than 3.11" when they have none at all. A refusal that
    misdescribes its cause is barely better than the ImportError it replaced.
    """
    text = HOOK.read_text(encoding="utf-8")
    absent_at = text.index("command -v python3")
    floor_at = text.index(_PREDICATE)
    assert absent_at < floor_at, "the absent-python3 check must precede the version predicate"
    # Backtick-free substring on purpose: the hook escapes backticks for `sh`
    # (`\`uv\``), so asserting the rendered form would fail on the source text.
    assert "nor" in text and "is on PATH, and the gate needs one of them." in text
    # And the two refusals must not be the same sentence. Count only ECHO lines:
    # the phrase also appears in the comment explaining why the branch exists, and
    # counting raw occurrences would fail on a file that is correct.
    # Filter by NOT-a-comment rather than startswith("echo"): the latter misses a
    # second refusal written with printf, a heredoc, or a continuation line, and
    # that failure mode is a false PASS. Excluding comments catches every output
    # verb for the same line count.
    refusals = [ln for ln in text.splitlines()
                if "older than 3.11" in ln and not ln.strip().startswith("#")]
    assert len(refusals) == 1, f"the too-old wording must appear in exactly one refusal, got {refusals}"


def test_the_refusal_names_the_floor_and_both_remedies() -> None:
    """A refusal that does not say WHY or HOW to fix it just relocates the confusion."""
    text = HOOK.read_text(encoding="utf-8")
    assert "requires-python >=3.11" in text, "the refusal must name pyproject's floor as the source"
    assert "3.11" in text
    assert "uv" in text
    assert "PATH" in text


@pytest.mark.parametrize("bad_argv", [["--version"], ["script.py"]])
def test_the_shim_itself_is_strict(tmp_path: Path, bad_argv: list[str]) -> None:
    """Self-check: the shim must reject argv shapes the guard never uses, so a test bug is loud."""
    d = _fake_python3(tmp_path, version=(3, 10))
    env = dict(os.environ, PATH=f"{d}{os.pathsep}{os.environ['PATH']}")
    r = subprocess.run(["python3", *bad_argv], env=env, capture_output=True,
                       text=True, timeout=30, check=False)
    assert r.returncode == 99
