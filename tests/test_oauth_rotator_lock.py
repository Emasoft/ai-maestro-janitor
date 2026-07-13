"""Tests for the cross-process OAuth-rotator-tick lock (audit §3.4, P3).

The daemon's 60 s `oauth-rotator-tick` and a human's manual `rotator.py tick`/
`switch`/`migrate-slots` are SEPARATE processes that both mutate state.json + the
live/slot keychain. Only a shared OS-level flock can stop them running the tick
mutation simultaneously (a lost `last_switch_at`/`live_429_streak` update, or two
near-simultaneous switches splitting the live credential). These tests pin the
lock's exclusion semantics with REAL flocks (same-process across two independent
open-file-descriptions AND a real second process) — no mocks. Mirrors
test_marketplace_lock.py.
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
    """Point the global-state dir (hence oauth-rotator-tick.lock) at a tmp dir."""
    os.environ["JANITOR_GLOBAL_STATE_DIR"] = str(tmp_path)


def test_acquire_returns_fd_then_releases(tmp_path: Path) -> None:
    """acquire_oauth_rotator_lock returns a usable fd; release frees it for re-acquire."""
    _isolate(tmp_path)
    fd = gs.acquire_oauth_rotator_lock()
    assert fd is not None
    gs.release_oauth_rotator_lock(fd)
    fd2 = gs.acquire_oauth_rotator_lock()
    assert fd2 is not None
    gs.release_oauth_rotator_lock(fd2)


def test_second_acquirer_is_blocked_while_held(tmp_path: Path) -> None:
    """A second acquisition returns None while the first fd still holds the flock."""
    _isolate(tmp_path)
    fd1 = gs.acquire_oauth_rotator_lock()
    assert fd1 is not None
    try:
        assert gs.acquire_oauth_rotator_lock() is None
    finally:
        gs.release_oauth_rotator_lock(fd1)
    fd3 = gs.acquire_oauth_rotator_lock()
    assert fd3 is not None
    gs.release_oauth_rotator_lock(fd3)


def test_context_manager_yields_true_then_false_then_true(tmp_path: Path) -> None:
    """oauth_rotator_lock() yields True when free, False to a nested attempt, True again after release."""
    _isolate(tmp_path)
    with gs.oauth_rotator_lock() as got_outer:
        assert got_outer is True
        with gs.oauth_rotator_lock() as got_inner:
            assert got_inner is False
    with gs.oauth_rotator_lock() as got_after:
        assert got_after is True


def test_oauth_lock_is_independent_of_marketplace_lock(tmp_path: Path) -> None:
    """The OAuth tick lock and the marketplace lock are SEPARATE flocks — holding one
    must NOT block the other (different machine-wide single-writer domains)."""
    _isolate(tmp_path)
    mfd = gs.acquire_marketplace_lock()
    assert mfd is not None
    try:
        ofd = gs.acquire_oauth_rotator_lock()
        assert ofd is not None, "the OAuth lock must not be blocked by the marketplace lock"
        gs.release_oauth_rotator_lock(ofd)
    finally:
        gs.release_marketplace_lock(mfd)


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
        fd = gs.acquire_oauth_rotator_lock()
        assert fd is not None, "holder failed to acquire"
        open({str(ready)!r}, 'w').close()
        deadline = time.time() + 30
        while not os.path.exists({str(release)!r}) and time.time() < deadline:
            time.sleep(0.05)
        gs.release_oauth_rotator_lock(fd)
    """)
    holder = subprocess.Popen([sys.executable, "-c", holder_src])
    try:
        deadline = time.time() + 10
        while not ready.exists() and time.time() < deadline:
            time.sleep(0.02)
        assert ready.exists(), "holder process never signalled ready"
        # While the other process holds the lock, we must be denied (skip path).
        assert gs.acquire_oauth_rotator_lock() is None
        # Release the holder, then we should be able to acquire.
        release.write_text("go")
        holder.wait(timeout=10)
        fd = gs.acquire_oauth_rotator_lock()
        assert fd is not None
        gs.release_oauth_rotator_lock(fd)
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=5)


def test_rotator_main_skips_mutating_command_when_lock_held(tmp_path: Path) -> None:
    """The single-writer guard lives in rotator.py main(), NOT the daemon wrapper: main()
    acquires the rotator-tick flock for every MUTATING command and SKIPS (returns 0, runs
    nothing) when another process holds it. This is what makes a daemon tick and a human's
    manual `rotator.py tick`/`switch` contend on the SAME lock — a daemon-side lock would
    only block the daemon's own subprocess and never see the manual run (audit §3.4)."""
    import importlib.util

    _isolate(tmp_path)
    rot_py = _PROJECT_ROOT / "scripts" / "oauth_rotator" / "rotator.py"
    spec = importlib.util.spec_from_file_location("rotator_lock_under_test", rot_py)
    assert spec and spec.loader
    rotator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rotator)
    # rotator imports the SAME cached `global_state` module the test uses, so its
    # gs.oauth_rotator_lock() contends on the same JANITOR_GLOBAL_STATE_DIR flock.
    ran: list[str] = []
    rotator.cmd_tick = lambda _: (ran.append("tick"), 0)[1]  # type: ignore[attr-defined]

    held = gs.acquire_oauth_rotator_lock()
    assert held is not None
    try:
        rc = rotator.main(["tick"])
        assert rc == 0
        assert ran == [], "main must NOT run cmd_tick while another holds the rotator lock"
    finally:
        gs.release_oauth_rotator_lock(held)
    # Lock free again → main runs the (monkeypatched) tick normally.
    assert rotator.main(["tick"]) == 0
    assert ran == ["tick"]


# ---- oauth_rotator_lock_wait: the CAPTURE path must not drop its write ------

def test_wait_variant_acquires_when_free(tmp_path: Path) -> None:
    """With the lock free it behaves exactly like the non-blocking form."""
    _isolate(tmp_path)
    with gs.oauth_rotator_lock_wait(timeout_s=1) as got:
        assert got is True


def test_wait_variant_waits_for_a_holder_instead_of_skipping(tmp_path: Path) -> None:
    """The whole point of the wait variant (audit 2026-07-13): a CAPTURE has already cost a
    human an interactive browser OAuth flow, so "skip, we'll get it next time" would throw
    that work away. It waits out the daemon's short tick and then proceeds. Real processes,
    real flock, no mocks."""
    _isolate(tmp_path)
    holder = subprocess.Popen([
        sys.executable, "-c", textwrap.dedent(f"""
            import os, sys, time
            os.environ["JANITOR_GLOBAL_STATE_DIR"] = {str(tmp_path)!r}
            sys.path.insert(0, {str(_LIB)!r})
            import global_state as gs
            fd = gs.acquire_oauth_rotator_lock()
            assert fd is not None
            print("HELD", flush=True)
            time.sleep(1.5)
            gs.release_oauth_rotator_lock(fd)
        """),
    ], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "HELD"    # the lock is genuinely taken
        assert gs.acquire_oauth_rotator_lock() is None       # the non-blocking form WOULD skip
        started = time.time()
        with gs.oauth_rotator_lock_wait(timeout_s=30) as got:
            waited = time.time() - started
            assert got is True, "the capture was dropped instead of waiting"
        assert waited >= 0.5, f"did not actually wait for the holder ({waited:.2f}s)"
    finally:
        holder.wait(timeout=30)


def test_wait_variant_gives_up_bounded_so_a_wedged_holder_cannot_hang_a_capture(
    tmp_path: Path,
) -> None:
    """Deadlock-proof: a holder that never lets go costs `timeout_s` and a clean False —
    never a hang. The caller writes NOTHING on that path, so no half-filed account."""
    _isolate(tmp_path)
    fd = gs.acquire_oauth_rotator_lock()
    assert fd is not None
    try:
        started = time.time()
        with gs.oauth_rotator_lock_wait(timeout_s=0.5, poll_s=0.05) as got:
            assert got is False
        assert time.time() - started < 10        # bounded, not hung
    finally:
        gs.release_oauth_rotator_lock(fd)
