"""Real end-to-end scenario test for `git_utils.clear_stale_index_lock`.

TRDD-VIDVBMLC (janitor#245, senior advisor review — ranked highest-value): the
existing unit suite (`tests/test_git_index_lock_recovery.py`) drives every
branch through an INJECTED `ps_snapshot` and a stubbed `_lock_is_held`, which
is exactly the shape that missed two real defects — both ENVIRONMENT-SHAPE
bugs that no injected-fake test can catch:

  (a) `.git` is a FILE in a linked worktree, so the old lookup returned
      "absent" — indistinguishable from "healthy".
  (b) the live-git check asked "is ANY git process running on this machine?",
      always true on a multi-session host, so the guard refused forever.

Both passed every injected-snapshot unit test. This file exercises the REAL
guard end to end: a genuine repo, a genuine linked worktree (created via a
real `git worktree add`), a genuine child process holding the lock file open
(probed via a real `lsof`), a genuine process-table snapshot (via a real
`ps` — never injected), and a genuine SECOND repo's live `git` process. No
mocking, no fakes, no monkeypatched guard functions — per this project's
"no mocked tests of the thing under test" rule, this is the only kind of
test that can prove the guard behaves correctly in its actual deployment
shape.

Each of the three scenarios is a distinct test, all sharing one fresh
main-repo + linked-worktree fixture built per test (`_make_worktree_repo`)
so any one of them can be run in isolation and reproduces cleanly. Every
subprocess spawned here is a real machine binary (`git`, the interpreter
itself for the lock-holder child) — none of it needs `@pytest.mark.
real_subprocess`: `git` operating inside a tmp-rooted repo and any Python
spawn are both allow-listed by this suite's write sandbox (see
`tests/sandbox_guard.py`), and `lsof`/`ps` are read-only observers that are
always allowed.

Per the card's own risk note: if a scenario here flakes on a loaded CI
runner (lsof/ps timing), that is SIGNAL about the guard's real-world
margins — investigate the guard, do not loosen this test.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.xdist_group(name="git_index_lock_e2e")]

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS / "lib"))

import git_utils  # type: ignore[import-not-found]  # noqa: E402

# This whole file is meaningless without the real machine binaries it drives — skip the
# module outright (not a per-test xfail, which would hide the gap in a green run summary)
# when any of them is missing, rather than degrading into a guess about what would happen.
if not (shutil.which("git") and shutil.which("lsof") and shutil.which("ps")):
    pytest.skip("git, lsof and ps must all be on PATH for this real end-to-end suite", allow_module_level=True)


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a real git command, asserting it succeeded — setup must never fail silently."""
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr}"
    return result


def _make_worktree_repo(base: Path) -> Path:
    """Build a real main repo with one commit, plus a real LINKED worktree off it.

    Returns the worktree's root — `<root>/.git` is a FILE (`gitdir: <path>`), the exact
    shape that made the pre-`_resolve_git_dir` code always report "absent" here.
    """
    main_repo = base / "main"
    main_repo.mkdir()
    _git(["init", "-q"], cwd=main_repo)
    (main_repo / "README.md").write_text("e2e fixture\n", encoding="utf-8")
    _git(["add", "README.md"], cwd=main_repo)
    _git(["-c", "user.email=e2e@example.com", "-c", "user.name=E2E", "commit", "-q", "-m", "init"], cwd=main_repo)

    worktree = base / "wt"
    _git(["worktree", "add", "-q", "-b", "wtbranch", str(worktree)], cwd=main_repo)
    assert (worktree / ".git").is_file(), "a linked worktree's .git must be a FILE, not a dir"
    return worktree


def _lock_path(worktree_root: Path) -> Path:
    """Where THIS worktree's index.lock really lives — via the worktree-aware resolver."""
    return git_utils._resolve_git_dir(worktree_root) / "index.lock"


def test_held_lock_in_a_linked_worktree_blocks_removal(tmp_path: Path) -> None:
    """A real child process holding the worktree's index.lock open (real lsof probe) must
    block removal ("held") — proving _resolve_git_dir's worktree-aware path resolution:
    the pre-fix code treated .git as a directory and would have reported "absent" here,
    silently skipping every guard below it."""
    worktree = _make_worktree_repo(tmp_path)
    lock_path = _lock_path(worktree)

    # A real Python child that opens the lock file and holds the fd — this is what a real
    # `lsof -a -- <lock_path>` sees as "held". It signals readiness on stdout so the parent
    # never guesses when the fd is actually open (no sleep-and-hope).
    holder_code = (
        "import sys, time\n"
        "f = open(sys.argv[1], 'wb')\n"
        "sys.stdout.write('ready\\n'); sys.stdout.flush()\n"
        "time.sleep(120)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", holder_code, str(lock_path)],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        ready = proc.stdout.readline() if proc.stdout else ""
        assert ready.strip() == "ready", f"holder child failed to open the lock file: {ready!r}"
        assert lock_path.is_file(), "the holder must have created the lock file"

        outcome = git_utils.clear_stale_index_lock(worktree, min_age_s=0)
        assert outcome == "held", f"a live fd-holder must block removal, got {outcome!r}"
        assert lock_path.is_file(), "a held lock must never be removed"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def test_stale_orphaned_lock_is_removed_and_renamed_aside(tmp_path: Path) -> None:
    """An aged, ownerless lock in a linked worktree (no live holder, real lsof + real ps
    snapshot both clear) must be removed — renamed aside to index.lock.stale-<epoch>, never
    unlinked outright, per the module's forensic-trace contract."""
    worktree = _make_worktree_repo(tmp_path)
    lock_path = _lock_path(worktree)
    lock_path.write_text("", encoding="utf-8")
    backdated = time.time() - 120
    os.utime(lock_path, (backdated, backdated))

    outcome = git_utils.clear_stale_index_lock(worktree, min_age_s=2)
    assert outcome == "removed", f"an aged, ownerless lock must be cleared, got {outcome!r}"
    assert not lock_path.is_file(), "the original lock path must be gone after removal"

    stale = list(lock_path.parent.glob("index.lock.stale-*"))
    assert len(stale) == 1, f"expected exactly one renamed-aside stale file, got {stale}"


def test_removal_still_clears_with_a_live_git_process_in_a_different_repo(tmp_path: Path) -> None:
    """The never-fires regression (janitor#245 follow-up): a real, live `git` process running
    in an UNRELATED second repository must NOT block removal here. The old, unscoped guard
    asked "is any git process alive anywhere on this machine?" — always true on a multi-
    session host — and refused forever; the scoped guard excludes it by cwd."""
    worktree = _make_worktree_repo(tmp_path)
    lock_path = _lock_path(worktree)
    lock_path.write_text("", encoding="utf-8")
    backdated = time.time() - 120
    os.utime(lock_path, (backdated, backdated))

    second_repo = tmp_path / "second"
    second_repo.mkdir()
    _git(["init", "-q"], cwd=second_repo)

    # A real, live, blocking `git` process anchored (by real OS cwd, not just `-C`) inside
    # the SECOND repo — it reads stdin until EOF, so it stays alive exactly as long as we
    # keep stdin open, no sleep involved.
    blocker = subprocess.Popen(
        ["git", "hash-object", "--stdin"],
        cwd=str(second_repo),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert blocker.poll() is None, "the second-repo git process must be alive before the check"

        outcome = git_utils.clear_stale_index_lock(worktree, min_age_s=2)
        assert outcome == "removed", (
            f"a live git process in an UNRELATED repo must never block removal here "
            f"(the never-fires regression), got {outcome!r}"
        )
        stale = list(lock_path.parent.glob("index.lock.stale-*"))
        assert len(stale) == 1, f"expected exactly one renamed-aside stale file, got {stale}"
    finally:
        if blocker.stdin:
            blocker.stdin.close()
        try:
            blocker.wait(timeout=5)
        except subprocess.TimeoutExpired:
            blocker.kill()
            blocker.wait(timeout=5)
