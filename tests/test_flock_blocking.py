"""Tests for the OS-keepalive blocking flock acquire (TRDD-324223a6, GROUP B).

Real flocks in an isolated global-state dir — no mocks. The load-bearing
properties: a free flock is acquired at once; a held flock makes the keeper WAIT
(rather than exit→respawn churn); ``should_stop`` (the kill-switch) breaks the
wait; and the keeper takes over the instant the holder releases.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import global_state as gs  # type: ignore[import-not-found]  # noqa: E402


def test_blocking_acquire_returns_fd_when_free(tmp_path, monkeypatch) -> None:
    """A free singleton flock is acquired immediately (no waiting)."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    fd = gs.acquire_singleton_flock_blocking(lambda: False, poll_s=1)
    assert fd is not None
    gs.release_singleton_flock(fd)


def test_blocking_acquire_bails_on_stop(tmp_path, monkeypatch) -> None:
    """When another daemon holds the flock and should_stop() is true (kill-switch),
    the keeper gives up (returns None) instead of waiting forever."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    held = gs.acquire_singleton_flock()
    assert held is not None
    try:
        assert gs.acquire_singleton_flock_blocking(lambda: True, poll_s=1) is None
    finally:
        gs.release_singleton_flock(held)


def test_blocking_acquire_takes_over_when_freed(tmp_path, monkeypatch) -> None:
    """The keeper acquires the flock the moment the prior holder releases it — the
    take-the-instant-it-dies behavior. should_stop releases the holder on its first
    call (standing in for the holder's death) and keeps the wait alive (False)."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    held = gs.acquire_singleton_flock()
    assert held is not None
    seen = {"released": False}

    def stop() -> bool:
        if not seen["released"]:
            gs.release_singleton_flock(held)   # the holder "dies" → flock frees
            seen["released"] = True
        return False

    fd = gs.acquire_singleton_flock_blocking(stop, poll_s=0)
    assert fd is not None
    assert seen["released"] is True
    gs.release_singleton_flock(fd)
