"""Attributed .git/index.lock recovery (TRDD-TUWUB0SG).

A git writer killed by a subprocess timeout (SIGKILL — git gets no cleanup
chance) orphans `.git/index.lock`; every later writer then fails until a human
deletes it. The recovery must never be a blanket delete: removal needs either
the OURS attribution (lock mtime at/after our own killed child's spawn) or the
ORPHAN triple (aged + empty + no live git in a process snapshot). Real tmp git
repos and real lock files; only the ps snapshot is injected (`ps_lines`) so the
no-live-git predicate is deterministic. The class fired live on this very repo
on 2026-08-18 23:32 (0-byte, 3-min-old lock, no holder).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import git_utils  # noqa: E402


def _repo(tmp_path: Path) -> Path:
    # cwd INSIDE the tmp tree — the suite's sandbox guard refuses mutating git
    # verbs whose cwd is the real repository, even with a tmp argv target.
    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
    return tmp_path


def _lock(repo: Path, *, age_s: float = 0.0, size: int = 0) -> Path:
    lock = repo / ".git" / "index.lock"
    lock.write_bytes(b"x" * size)
    if age_s:
        past = time.time() - age_s
        os.utime(lock, (past, past))
    return lock


NO_GIT = ["ps-header", "python3.12", "zsh", "launchd"]
WITH_GIT = ["ps-header", "python3.12", "git", "zsh"]


def test_ours_after_timeout_is_removed_regardless_of_age(tmp_path: Path) -> None:
    """A lock born at/after our child's spawn is OUR killed git's corpse — removed."""
    repo = _repo(tmp_path)
    spawn = time.time() - 5
    lock = _lock(repo)  # fresh mtime, after spawn
    assert git_utils.recover_stale_index_lock(repo, spawn_ts=spawn, ps_lines=WITH_GIT)
    assert not lock.exists()


def test_orphan_triple_is_removed(tmp_path: Path) -> None:
    """Aged + empty + no live git: the measured live shape of 2026-08-18 23:32."""
    repo = _repo(tmp_path)
    lock = _lock(repo, age_s=180)
    assert git_utils.recover_stale_index_lock(repo, ps_lines=NO_GIT)
    assert not lock.exists()


def test_fresh_lock_without_spawn_ts_is_left_alone(tmp_path: Path) -> None:
    """No ours-attribution and under min_age: could be a live racer — untouched."""
    repo = _repo(tmp_path)
    lock = _lock(repo)  # age ~0
    assert not git_utils.recover_stale_index_lock(repo, ps_lines=NO_GIT)
    assert lock.exists()


def test_live_git_process_blocks_orphan_removal(tmp_path: Path) -> None:
    """An aged empty lock is still NOT removed while any git process is alive."""
    repo = _repo(tmp_path)
    lock = _lock(repo, age_s=600)
    assert not git_utils.recover_stale_index_lock(repo, ps_lines=WITH_GIT)
    assert lock.exists()


def test_nonempty_lock_is_never_orphan_removed(tmp_path: Path) -> None:
    """Bytes in the lock mean a git was writing the new index — live work, untouched."""
    repo = _repo(tmp_path)
    lock = _lock(repo, age_s=600, size=64)
    assert not git_utils.recover_stale_index_lock(repo, ps_lines=NO_GIT)
    assert lock.exists()


def test_no_lock_reports_false(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert not git_utils.recover_stale_index_lock(repo, ps_lines=NO_GIT)


def test_real_producer_a_commit_killed_in_its_hook_leaves_NO_lock(tmp_path: Path) -> None:
    """MEASURED against the real producer (fleet ai_review warning 2026-08-18: verify
    input shapes against the producer, not the card's prose — and the measurement
    REFUTED the card's assumed shape): a genuine `git commit` SIGKILLed by a genuine
    subprocess timeout while its pre-commit hook runs leaves NO index.lock — git does
    not hold the lock across the hook. So the ours-attribution (`spawn_ts`) path is a
    harmless NO-OP for this shape (no lock ⇒ recover returns False), and the shape the
    incident actually produced — an aged 0-byte orphan of an unknown producer, measured
    live 2026-08-18 23:32 — is the triple-predicate path the other tests pin. Pinning
    the refutation keeps the next reader from re-deriving the wrong mechanism."""
    repo = _repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    (repo / "f.txt").write_text("x")
    subprocess.run(["git", "-C", str(repo), "add", "f.txt"], check=True)
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nsleep 30\n")
    hook.chmod(0o755)
    spawn = time.time()
    try:
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "m"],
            capture_output=True, text=True, timeout=1,
        )
        raise AssertionError("the hooked commit was expected to time out")
    except subprocess.TimeoutExpired:
        pass
    lock = repo / ".git" / "index.lock"
    assert not lock.exists(), "git now holds index.lock across pre-commit — mechanism changed"
    # ...and the ours-path recovery is a clean no-op on the lockless aftermath.
    assert not git_utils.recover_stale_index_lock(repo, spawn_ts=spawn, ps_lines=WITH_GIT)


def test_recovered_repo_is_writable_again(tmp_path: Path) -> None:
    """End-to-end: orphaned lock blocks a real commit; recovery makes it succeed."""
    repo = _repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    (repo / "f.txt").write_text("x")
    subprocess.run(["git", "-C", str(repo), "add", "f.txt"], check=True)
    _lock(repo, age_s=180)
    blocked = subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "m"], capture_output=True, text=True,
    )
    assert blocked.returncode != 0 and "index.lock" in blocked.stderr
    assert git_utils.recover_stale_index_lock(repo, ps_lines=NO_GIT)
    ok = subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "m"], capture_output=True, text=True,
    )
    assert ok.returncode == 0, ok.stderr
