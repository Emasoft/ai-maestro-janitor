"""`git_utils.recover_own_index_lock` — the SPAWNER-side attribution (TRDD-TUWUB0SG).

`clear_stale_index_lock` (janitor#245) is the OBSERVER recovery: it cannot tell a
fresh orphan from a live writer, so a young lock is "too-young" for min_age_s. A
spawner whose `subprocess.run(timeout=…)` just SIGKILLed its own git CAN attribute
a lock whose mtime is at/after that spawn — this helper removes exactly that, and
only behind the same lsof holder probe (G0). Real tmp git repos; only the probe is
stubbed where a deterministic verdict is needed.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "lib"))

import git_utils  # noqa: E402


def _repo(tmp_path: Path) -> Path:
    # cwd INSIDE the tmp tree — the suite's sandbox guard refuses mutating git
    # verbs whose cwd is the real repository, even with a tmp argv target.
    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
    return tmp_path


def _lock(repo: Path, *, age_s: float = 0.0) -> Path:
    lock = repo / ".git" / "index.lock"
    lock.write_bytes(b"")
    if age_s:
        past = time.time() - age_s
        os.utime(lock, (past, past))
    return lock


def test_lock_born_after_our_spawn_is_removed_and_repo_commits_again(
    monkeypatch, tmp_path: Path
) -> None:
    """OURS attribution: mtime at/after the killed child's spawn ⇒ removed with no age
    wait — and the repo is genuinely writable again (a real commit succeeds)."""
    monkeypatch.setattr(git_utils, "_lock_is_held", lambda _: False)
    repo = _repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    (repo / "f.txt").write_text("x")
    subprocess.run(["git", "-C", str(repo), "add", "f.txt"], check=True)
    spawn = time.time() - 5
    lock = _lock(repo)
    assert git_utils.recover_own_index_lock(repo, spawn)
    assert not lock.exists()
    ok = subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "m"], capture_output=True, text=True,
    )
    assert ok.returncode == 0, ok.stderr


def test_lock_predating_our_spawn_is_not_ours(monkeypatch, tmp_path: Path) -> None:
    """A lock older than our spawn belongs to someone else — untouched, defer to
    the observer recovery with its full guard set."""
    monkeypatch.setattr(git_utils, "_lock_is_held", lambda _: False)
    repo = _repo(tmp_path)
    lock = _lock(repo, age_s=300)
    assert not git_utils.recover_own_index_lock(repo, time.time() - 1)
    assert lock.exists()


def test_held_or_unprobeable_lock_is_never_removed(monkeypatch, tmp_path: Path) -> None:
    """G0 fail-closed: a held lock (True) or a blind probe (None) removes nothing."""
    repo = _repo(tmp_path)
    for verdict in (True, None):
        lock = _lock(repo)
        monkeypatch.setattr(git_utils, "_lock_is_held", lambda _p, v=verdict: v)
        assert not git_utils.recover_own_index_lock(repo, time.time() - 5)
        assert lock.exists()
        lock.unlink()


def test_no_lock_reports_false(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert not git_utils.recover_own_index_lock(repo, time.time())


# The `timeout=1` below is the test's INSTRUMENT — it is how the commit gets killed mid-hook.
# The suite-wide scaling seam would stretch it to 10 s (TRDD-7NSRD8OV); the `sleep 30` hook
# means it would still fire, but 9 s later for nothing. A test that drives timeout behaviour
# owns its own scale.
@pytest.mark.no_timeout_scale
def test_real_producer_a_commit_killed_in_its_hook_leaves_NO_lock(tmp_path: Path) -> None:
    """MEASURED against the real producer (fleet ai_review warning 2026-08-18: verify
    input shapes against the producer, not a card's prose — and the measurement
    REFUTED the card's assumed shape): a genuine `git commit` SIGKILLed by a genuine
    subprocess timeout while its pre-commit hook runs leaves NO index.lock — git does
    not hold the lock across the hook. The ours-path is then a clean no-op, and the
    shape the live incident actually produced (an aged 0-byte orphan of an unknown
    producer, 2026-08-18 23:32) is `clear_stale_index_lock`'s territory. Pinned so
    the next reader cannot re-derive the wrong mechanism."""
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
    assert not (repo / ".git" / "index.lock").exists(), \
        "git now holds index.lock across pre-commit — mechanism changed; revisit TUWUB0SG"
    assert not git_utils.recover_own_index_lock(repo, spawn)
