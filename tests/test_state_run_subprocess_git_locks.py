"""state.run_subprocess must never let a child take .git/index.lock (janitor#245).

A read-only `git status`/`git diff` still WRITES `.git/index.lock` for its optional
stat-cache write-back, and the ~5-minute heartbeat overlapping a minutes-long
`publish.py` commit made that collision SCHEDULED, not unlucky — it killed real
publishes. `GIT_OPTIONAL_LOCKS=0` is git's own documented escape hatch; every child
spawned through the shared helper must inherit it.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import state  # noqa: E402


def test_run_subprocess_child_env_carries_git_optional_locks_off() -> None:
    """The spawned child's own environment must report GIT_OPTIONAL_LOCKS=0."""
    proc = state.run_subprocess(
        [sys.executable, "-c", "import os; print(os.environ.get('GIT_OPTIONAL_LOCKS', ''))"],
    )
    assert proc is not None
    assert proc.stdout.strip() == "0"


def test_run_subprocess_still_inherits_the_rest_of_the_parent_env(monkeypatch) -> None:
    """The injected var is additive — it must not clobber the rest of os.environ."""
    monkeypatch.setenv("JANITOR_TEST_MARKER_76XSELZ7", "present")
    proc = state.run_subprocess(
        [sys.executable, "-c", "import os; print(os.environ.get('JANITOR_TEST_MARKER_76XSELZ7', ''))"],
    )
    assert proc is not None
    assert proc.stdout.strip() == "present"
