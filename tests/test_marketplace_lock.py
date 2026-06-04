"""Tests for the cross-process marketplace-operation lock (root cause D).

The daemon's bulk `claude plugin marketplace update` and the per-session
single-market updates are SEPARATE processes; only a shared OS-level flock
can stop them running the marketplace mutation simultaneously — the race
issue #7 said per-project PID dedup could not prevent. These tests pin the
lock's exclusion semantics with REAL flocks (same-process across two
independent open-file-descriptions AND a real second process) — no mocks.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LIB = _PROJECT_ROOT / "scripts" / "lib"
sys.path.insert(0, str(_LIB))

import global_state as gs  # noqa: E402


def _isolate(tmp_path: Path) -> None:
    """Point the global-state dir (hence marketplace-op.lock) at a tmp dir."""
    os.environ["JANITOR_GLOBAL_STATE_DIR"] = str(tmp_path)


def test_acquire_returns_fd_then_releases(tmp_path: Path) -> None:
    """acquire_marketplace_lock returns a usable fd; release frees it for re-acquire."""
    _isolate(tmp_path)
    fd = gs.acquire_marketplace_lock()
    assert fd is not None
    gs.release_marketplace_lock(fd)
    fd2 = gs.acquire_marketplace_lock()
    assert fd2 is not None
    gs.release_marketplace_lock(fd2)


def test_second_acquirer_is_blocked_while_held(tmp_path: Path) -> None:
    """A second acquisition returns None while the first fd still holds the flock."""
    _isolate(tmp_path)
    fd1 = gs.acquire_marketplace_lock()
    assert fd1 is not None
    try:
        # Real flock conflicts across independent open-file-descriptions even
        # within one process (flock(2)) — the same kernel guarantee that keeps
        # the daemon process and a detector process from colliding.
        assert gs.acquire_marketplace_lock() is None
    finally:
        gs.release_marketplace_lock(fd1)
    fd3 = gs.acquire_marketplace_lock()
    assert fd3 is not None
    gs.release_marketplace_lock(fd3)


def test_context_manager_yields_true_then_false_then_true(tmp_path: Path) -> None:
    """marketplace_lock() yields True when free, False to a nested attempt, True again after release."""
    _isolate(tmp_path)
    with gs.marketplace_lock() as got_outer:
        assert got_outer is True
        with gs.marketplace_lock() as got_inner:
            assert got_inner is False
    with gs.marketplace_lock() as got_after:
        assert got_after is True


def test_cross_process_exclusion(tmp_path: Path) -> None:
    """A real second process holding the lock forces us to skip; releasing lets us acquire."""
    _isolate(tmp_path)
    ready = tmp_path / "ready"
    release = tmp_path / "release"
    holder_src = textwrap.dedent(f"""
        import os, sys, time
        sys.path.insert(0, {str(_LIB)!r})
        os.environ['JANITOR_GLOBAL_STATE_DIR'] = {str(tmp_path)!r}
        import global_state as gs
        fd = gs.acquire_marketplace_lock()
        assert fd is not None, "holder failed to acquire"
        open({str(ready)!r}, 'w').close()
        deadline = time.time() + 30
        while not os.path.exists({str(release)!r}) and time.time() < deadline:
            time.sleep(0.05)
        gs.release_marketplace_lock(fd)
    """)
    holder = subprocess.Popen([sys.executable, "-c", holder_src])
    try:
        deadline = time.time() + 10
        while not ready.exists() and time.time() < deadline:
            time.sleep(0.02)
        assert ready.exists(), "holder process never signalled ready"
        # While the other process holds the lock, we must be denied (skip path).
        assert gs.acquire_marketplace_lock() is None
        # Release the holder, then we should be able to acquire.
        release.write_text("go")
        holder.wait(timeout=10)
        fd = gs.acquire_marketplace_lock()
        assert fd is not None
        gs.release_marketplace_lock(fd)
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=5)
