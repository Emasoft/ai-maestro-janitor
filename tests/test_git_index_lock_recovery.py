"""`git_utils.clear_stale_index_lock` — the RECOVERY half of janitor#245.

Owner ruling: prevention (GIT_OPTIONAL_LOCKS=0 on every READER — see
`test_git_optional_locks_guard.py`) stops readers from ever taking
`.git/index.lock`, but it cannot stop a WRITER (a real `git add`/`git commit`)
from being SIGKILLed, crashing, or OOM-killed mid-write, which leaves the lock
file behind forever — stalling an unattended run indefinitely on a lock
nothing will ever release.

These tests drive every branch through the INJECTED `ps_snapshot` parameter —
never a real `pgrep`/`ps | grep` (which would match its own shell's argv) and
never a real subprocess — so nothing here spawns a process or touches a real
git repository. `tmp_path` supplies a throwaway `.git/index.lock` file.
"""

from __future__ import annotations

import errno
import sys
import time
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS / "lib"))

import git_utils  # type: ignore[import-not-found]  # noqa: E402

# Captured BEFORE the autouse fixture below patches it, so the one test that
# needs the REAL probe can restore it explicitly.
_REAL_LOCK_IS_HELD = git_utils._lock_is_held


@pytest.fixture(autouse=True)
def _no_real_lsof(monkeypatch):  # pyright: ignore[reportUnusedFunction]  # autouse: pytest resolves it by registration, never by name
    """Every test in this module is UNIT-level and must stay deterministic —
    G0 (`git_utils._lock_is_held`) shells out to a real `lsof` in production,
    which this fixture stubs to "not held" (False) by default so every test
    exercises the SAME cwd/age guards it did before G0 was introduced.
    Individual tests override this (to "held" / "no-probe" / the real probe)
    via their own `monkeypatch.setattr` call, which layers on top and is
    undone first at teardown."""
    monkeypatch.setattr(git_utils, "_lock_is_held", lambda _: False)


# A `ps -eo pid,ppid,etime,command` snapshot with NO git process running —
# just an unrelated shell and this test runner itself.
_PS_NO_GIT = (
    "  PID  PPID     ELAPSED COMMAND\n"
    "    1     0    10:00:00 /sbin/launchd\n"
    " 4242     1       05:12 /bin/zsh -i\n"
    " 9999  4242       00:03 uv run pytest -q\n"
)

# A snapshot WITH a live git process (e.g. a concurrent `git commit`).
_PS_WITH_GIT = _PS_NO_GIT + " 5150  4242       00:01 git commit -m wip\n"

# A snapshot where "git" only appears inside an unrelated argv token (a path
# component) — must NOT be mistaken for a live git process.
_PS_GIT_LOOKALIKE = _PS_NO_GIT + " 6161  4242       00:02 /usr/bin/python3 scripts/lib/git_utils.py\n"


def _make_lock(tmp_path: Path, *, age_s: float) -> Path:
    """Create `<tmp_path>/.git/index.lock` with mtime `age_s` seconds in the past."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir(parents=True, exist_ok=True)
    lock = git_dir / "index.lock"
    lock.write_text("", encoding="utf-8")
    stamp = time.time() - age_s
    import os

    os.utime(lock, (stamp, stamp))
    return lock


def test_absent_lock_is_not_an_error(tmp_path):
    """No `.git/index.lock` at all: report 'absent', touch nothing."""
    (tmp_path / ".git").mkdir()
    outcome = git_utils.clear_stale_index_lock(tmp_path, min_age_s=60, ps_snapshot=_PS_NO_GIT)
    assert outcome == "absent"


def test_removed_when_stale_and_no_git(tmp_path):
    """A lock older than min_age_s, with no live git in the snapshot, is removed."""
    lock = _make_lock(tmp_path, age_s=300)
    outcome = git_utils.clear_stale_index_lock(tmp_path, min_age_s=60, ps_snapshot=_PS_NO_GIT)
    assert outcome == "removed"
    assert not lock.exists()


def test_kept_when_a_live_git_appears_in_the_snapshot(tmp_path):
    """Even a very OLD lock is left alone if the snapshot shows a live git —
    age alone must never override the live-process guard."""
    lock = _make_lock(tmp_path, age_s=3600)
    outcome = git_utils.clear_stale_index_lock(tmp_path, min_age_s=60, ps_snapshot=_PS_WITH_GIT)
    assert outcome == "live-git"
    assert lock.exists()


def test_kept_when_too_young(tmp_path):
    """A lock younger than min_age_s is left alone even with no git in the
    snapshot — a fresh lock likely belongs to a git that hasn't shown up in
    the (possibly slightly stale) snapshot yet."""
    lock = _make_lock(tmp_path, age_s=5)
    outcome = git_utils.clear_stale_index_lock(tmp_path, min_age_s=60, ps_snapshot=_PS_NO_GIT)
    assert outcome == "too-young"
    assert lock.exists()


def test_git_lookalike_argv_does_not_block_removal(tmp_path):
    """A process whose argv merely MENTIONS 'git' (e.g. a path to
    git_utils.py) must not be mistaken for a live git — only the literal
    `git` executable token counts."""
    lock = _make_lock(tmp_path, age_s=300)
    outcome = git_utils.clear_stale_index_lock(
        tmp_path, min_age_s=60, ps_snapshot=_PS_GIT_LOOKALIKE
    )
    assert outcome == "removed"
    assert not lock.exists()


def test_no_snapshot_injected_gathers_one_rather_than_skipping_the_guard(monkeypatch, tmp_path):
    """`ps_snapshot=None` GATHERS a snapshot — it never degrades to age-only."""
    calls = []
    monkeypatch.setattr(
        git_utils, "_gather_ps_snapshot", lambda: (calls.append(1), _PS_NO_GIT)[1]
    )
    lock = _make_lock(tmp_path, age_s=300)
    outcome = git_utils.clear_stale_index_lock(tmp_path, min_age_s=60)
    assert calls, "an omitted snapshot must be gathered, not skipped"
    assert outcome == "removed"
    assert not lock.exists()


def test_ungatherable_snapshot_removes_nothing(monkeypatch, tmp_path):
    """FAIL-CLOSED. If the snapshot cannot be taken, guard 1 cannot be evaluated,
    so nothing is removed — however old the lock is.

    This is the case the previous version got wrong: it defaulted to "no live
    git" and let the AGE guard decide alone. A live writer that has legitimately
    held the lock for longer than `min_age_s` (a big `git add`, a slow pre-commit
    hook) would then have its lock deleted out from under it — corrupting the
    very concurrent write guard 1 exists to protect."""
    monkeypatch.setattr(git_utils, "_gather_ps_snapshot", lambda: None)
    lock = _make_lock(tmp_path, age_s=86400)
    outcome = git_utils.clear_stale_index_lock(tmp_path, min_age_s=60)
    assert outcome == "no-snapshot"
    assert lock.exists(), "a lock must survive when the live-git guard is blind"


def test_gathered_snapshot_showing_live_git_blocks_removal(monkeypatch, tmp_path):
    """The gathered path honours guard 1 exactly as an injected snapshot does."""
    monkeypatch.setattr(git_utils, "_gather_ps_snapshot", lambda: _PS_WITH_GIT)
    lock = _make_lock(tmp_path, age_s=86400)
    outcome = git_utils.clear_stale_index_lock(tmp_path, min_age_s=60)
    assert outcome == "live-git"
    assert lock.exists()


def test_gather_ps_snapshot_sees_the_real_process_table():
    """The real gatherer returns a usable table (it is not stubbed everywhere)."""
    snap = git_utils._gather_ps_snapshot()
    assert snap is not None and len(snap.splitlines()) > 1


def test_boundary_age_exactly_min_age_s_is_removable(tmp_path):
    """A lock exactly `min_age_s` old is NOT 'too-young' (age_s < min_age_s is
    the refusal condition, so equality clears it) — pin the boundary."""
    lock = _make_lock(tmp_path, age_s=60.5)
    outcome = git_utils.clear_stale_index_lock(tmp_path, min_age_s=60, ps_snapshot=_PS_NO_GIT)
    assert outcome == "removed"
    assert not lock.exists()


def test_never_raises_on_a_missing_git_dir(tmp_path):
    """No `.git/` directory at all (not even created) — still 'absent', never an exception."""
    outcome = git_utils.clear_stale_index_lock(tmp_path, min_age_s=60, ps_snapshot=_PS_NO_GIT)
    assert outcome == "absent"


def test_live_git_in_a_different_repo_does_not_block_removal(monkeypatch, tmp_path):
    """A git pid whose cwd is confirmed OUTSIDE this repo cannot be holding THIS repo's
    index.lock, so it must not block removal — the janitor#245 follow-up bug this module
    guards against (a bare 'any git process alive anywhere' check refuses forever)."""
    other_repo = tmp_path.parent / "some-other-repo"
    other_repo.mkdir(exist_ok=True)
    monkeypatch.setattr(git_utils, "_pid_cwd", lambda _: other_repo)
    lock = _make_lock(tmp_path, age_s=300)
    outcome = git_utils.clear_stale_index_lock(tmp_path, min_age_s=60, ps_snapshot=_PS_WITH_GIT)
    assert outcome == "removed"
    assert not lock.exists()


def test_live_git_in_this_repo_blocks_removal(monkeypatch, tmp_path):
    """A git pid whose cwd resolves to THIS repo genuinely could be holding the lock —
    removal is blocked."""
    monkeypatch.setattr(git_utils, "_pid_cwd", lambda _: tmp_path.resolve())
    lock = _make_lock(tmp_path, age_s=300)
    outcome = git_utils.clear_stale_index_lock(tmp_path, min_age_s=60, ps_snapshot=_PS_WITH_GIT)
    assert outcome == "live-git"
    assert lock.exists()


def test_live_git_with_unresolvable_cwd_blocks_removal(monkeypatch, tmp_path):
    """A git pid whose cwd could NOT be resolved (lsof failed, pid gone, permission denied)
    fails CLOSED — treated as possibly holding the lock, never silently excluded."""
    monkeypatch.setattr(git_utils, "_pid_cwd", lambda _: None)
    lock = _make_lock(tmp_path, age_s=300)
    outcome = git_utils.clear_stale_index_lock(tmp_path, min_age_s=60, ps_snapshot=_PS_WITH_GIT)
    assert outcome == "live-git"
    assert lock.exists()


# --- G0 (`_lock_is_held`) — the PRIMARY, file-holder-probe guard ----------


def test_held_by_a_live_process_blocks_removal(monkeypatch, tmp_path):
    """G0 confirming a live holder blocks removal outright ('held'), before
    the cwd/age guards below it even run — this is the guard that catches a
    libgit2 GUI client with NO `git` process in the ps table at all."""
    monkeypatch.setattr(git_utils, "_lock_is_held", lambda _: True)
    lock = _make_lock(tmp_path, age_s=3600)
    outcome = git_utils.clear_stale_index_lock(tmp_path, min_age_s=60, ps_snapshot=_PS_NO_GIT)
    assert outcome == "held"
    assert lock.exists()


def test_unknown_probe_result_fails_closed(monkeypatch, tmp_path):
    """G0 returning None (lsof missing, errored, or timed out) fails CLOSED —
    'no-probe', nothing removed. Unknown must never be treated as 'not held'."""
    monkeypatch.setattr(git_utils, "_lock_is_held", lambda _: None)
    lock = _make_lock(tmp_path, age_s=3600)
    outcome = git_utils.clear_stale_index_lock(tmp_path, min_age_s=60, ps_snapshot=_PS_NO_GIT)
    assert outcome == "no-probe"
    assert lock.exists()


def test_lock_is_held_returns_false_for_a_real_unheld_file(tmp_path, monkeypatch):
    """The ONE test in this module that shells out to a REAL `lsof`: proves
    `_lock_is_held` genuinely reports 'not held' (False) for an ordinary file
    nothing has open. Every other test in this module injects a fake result
    instead — a real lsof call would make outcomes depend on the test host's
    process table."""
    monkeypatch.setattr(git_utils, "_lock_is_held", _REAL_LOCK_IS_HELD)
    lock = _make_lock(tmp_path, age_s=3600)
    assert git_utils._lock_is_held(lock) is False


# --- Error-conflation fix: only ENOENT may report "removed" ---------------


def test_enoent_during_removal_reports_removed(monkeypatch, tmp_path):
    """Another process (or a concurrent recovery pass) already removed the
    lock in the gap before our rename lands — `os.replace` raises ENOENT,
    which must still report success: someone else already achieved the goal."""
    _make_lock(tmp_path, age_s=3600)

    def raise_enoent(*_):
        raise OSError(errno.ENOENT, "No such file or directory")

    monkeypatch.setattr(git_utils.os, "replace", raise_enoent)
    outcome = git_utils.clear_stale_index_lock(tmp_path, min_age_s=60, ps_snapshot=_PS_NO_GIT)
    assert outcome == "removed"


def test_eacces_during_removal_reports_error_not_removed(monkeypatch, tmp_path):
    """A permission error must be reported as a real failure, never conflated
    with success. This is the bug the advisor found: `except OSError: return
    "removed"` used to report EACCES/EPERM as if the lock had been cleared."""
    lock = _make_lock(tmp_path, age_s=3600)

    def raise_eacces(*_):
        raise OSError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(git_utils.os, "replace", raise_eacces)
    outcome = git_utils.clear_stale_index_lock(tmp_path, min_age_s=60, ps_snapshot=_PS_NO_GIT)
    assert outcome == "error"
    assert lock.exists(), "a real error must leave the lock in place, never silently vanish"


# --- TOCTOU guard — the identity re-check right before removal ------------


def test_raced_when_lock_identity_changes_before_removal(monkeypatch, tmp_path):
    """If the lock's identity (inode or mtime) changes between the initial
    stat and the stat taken immediately before removal, back off ('raced')
    rather than deleting a lock a fresh writer may have just taken — this is
    what stops session A from destroying a brand-new lock that session B (or
    a genuine new writer) created in the gap between A's checks."""
    lock = _make_lock(tmp_path, age_s=3600)
    original_stat = Path.stat
    calls = {"n": 0}

    def racy_stat(self, *a, **kw):
        # Only the lock file itself — never `.git` or the eventual renamed
        # marker — so this doesn't perturb the OTHER stat() calls the
        # function (or pathlib internals like `is_file()`) also make.
        if self.name == "index.lock":
            calls["n"] += 1
            if calls["n"] == 2:
                # Simulate a fresh writer replacing the lock's content
                # between the two checks `clear_stale_index_lock` makes.
                self.write_text("a fresh writer's own lock content", encoding="utf-8")
        return original_stat(self, *a, **kw)

    monkeypatch.setattr(Path, "stat", racy_stat)
    outcome = git_utils.clear_stale_index_lock(tmp_path, min_age_s=60, ps_snapshot=_PS_NO_GIT)
    assert outcome == "raced"
    assert lock.exists(), "a raced lock must survive untouched"
    assert lock.read_text(encoding="utf-8") == "a fresh writer's own lock content"


# --- Rename-aside instead of unlink ----------------------------------------


def test_removed_renames_aside_instead_of_unlinking(tmp_path):
    """Successful removal RENAMES the lock to `index.lock.stale-<epoch>` in
    the same directory rather than unlinking it outright — same unblocking
    effect for git, but keeps a forensic trace and needs no human permission
    (this project's safe-delete philosophy: a recoverable action is not a
    deletion)."""
    lock = _make_lock(tmp_path, age_s=3600)
    outcome = git_utils.clear_stale_index_lock(tmp_path, min_age_s=60, ps_snapshot=_PS_NO_GIT)
    assert outcome == "removed"
    assert not lock.exists(), "the original index.lock path must be gone"
    stale_files = list(lock.parent.glob("index.lock.stale-*"))
    assert len(stale_files) == 1, "exactly one renamed-aside stale marker must remain"
