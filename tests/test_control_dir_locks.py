"""Tests for the three COORDINATION locks moving to control_dir() (TRDD-QK7M2B0X phase B).

The mode flags moved in phase A; the locks are the load-bearing half. A flag is data, so a
reader probing both paths cannot miss it — but a flock is kernel state bound to an INODE,
and two processes locking two different paths BOTH win. That is why the transition is a
dual-LOCK (new + old, held together) rather than the dual-READ the flags use, and why the
tests below check the upgrade window in BOTH directions rather than only the end state.

Isolation: every test points `JANITOR_CONTROL_DIR` and `JANITOR_GLOBAL_STATE_DIR` at fresh
tmp dirs, so nothing here can contend on the real machine's control plane. The in-process
"foreign holder" is a plain `os.open` + `flock`, which is exactly what a previous release's
code does — flock(2) conflicts across independent open file descriptions even within one
process, so no subprocess is needed to prove exclusion.
"""

from __future__ import annotations

import fcntl
import os
import sys
from pathlib import Path
from typing import Iterator

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

# The three locks a SECOND chore owner (the ai-maestro server) also contends on, paired
# with the janitor entry point that takes each one.
_LOCKS = ("marketplace-op.lock", "oauth-rotator-tick.lock", "settings-ensurer.lock")


@pytest.fixture
def dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Isolated (control_dir, global_state_dir) pair. Neither is pre-created: acquiring a
    lock must create the control dir itself, which is half of what makes the fixed path
    usable by a foreign program that never ran the janitor's installer."""
    control = tmp_path / "control"
    gsd = tmp_path / "global-state"
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(control))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(gsd))
    if "global_state" in sys.modules:
        del sys.modules["global_state"]
    return control, gsd


def _gs():
    import global_state

    return global_state


def _acquirers(gs) -> dict[str, tuple]:
    """{lock filename: (acquire, release)} for the three coordination locks."""
    return {
        "marketplace-op.lock": (gs.acquire_marketplace_lock, gs.release_marketplace_lock),
        "oauth-rotator-tick.lock": (gs.acquire_oauth_rotator_lock, gs.release_oauth_rotator_lock),
        "settings-ensurer.lock": (gs.acquire_settings_ensurer_lock, gs.release_settings_ensurer_lock),
    }


@pytest.fixture
def foreign() -> Iterator[list[int]]:
    """Hold flocks the way an outside process does — raw open+flock, no janitor code —
    and guarantee they are released even when a test fails mid-assert."""
    fds: list[int] = []

    def _hold(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fds.append(fd)

    _hold.fds = fds  # type: ignore[attr-defined]
    try:
        yield _hold  # type: ignore[misc]
    finally:
        for fd in fds:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(fd)
            except OSError:
                pass


@pytest.mark.parametrize("lock", _LOCKS)
def test_lock_file_is_created_in_control_dir(dirs: tuple[Path, Path], lock: str) -> None:
    """Acquiring a coordination lock creates it at the FIXED control path — the literal
    path an ai-maestro server hardcodes, with no janitor code involved on its side."""
    control, _gsd = dirs
    gs = _gs()
    acquire, release = _acquirers(gs)[lock]
    handle = acquire()
    assert handle is not None
    try:
        assert (control / lock).is_file(), f"{lock} was not created at the fixed control path"
    finally:
        release(handle)


@pytest.mark.parametrize("lock", _LOCKS)
def test_foreign_holder_on_control_path_forces_skip(
    dirs: tuple[Path, Path], foreign, lock: str
) -> None:
    """A foreign owner holding the CONTROL-path lock excludes the janitor. This is the
    whole point of the move: before it, the server's lock and the janitor's lock were
    different inodes, so the 90 s handoff-window backstop excluded nobody."""
    control, _gsd = dirs
    gs = _gs()
    acquire, _release = _acquirers(gs)[lock]
    foreign(control / lock)
    assert acquire() is None


@pytest.mark.parametrize("lock", _LOCKS)
def test_old_path_holder_still_excludes_during_upgrade_window(
    dirs: tuple[Path, Path], foreign, lock: str
) -> None:
    """THE upgrade-window case. A not-yet-updated session holds ONLY the old
    global_state_dir() path. A new-code peer that locked just the new path would proceed
    and both would run the chore — so the new code must take the old inode too, and skip."""
    _control, gsd = dirs
    gs = _gs()
    acquire, _release = _acquirers(gs)[lock]
    foreign(gsd / lock)
    assert acquire() is None


@pytest.mark.parametrize("lock", _LOCKS)
def test_partial_acquisition_releases_the_half_it_took(
    dirs: tuple[Path, Path], foreign, lock: str
) -> None:
    """Losing on the OLD path must not leave the NEW path locked. A leaked half would
    wedge every future acquirer — including the server — behind a lock nobody holds on
    purpose, which is worse than the race the dual-lock exists to close."""
    control, gsd = dirs
    gs = _gs()
    acquire, _release = _acquirers(gs)[lock]
    foreign(gsd / lock)
    assert acquire() is None  # denied on the old half
    # The new half must be free: prove it by taking it the foreign way.
    probe = os.open(str(control / lock), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)  # raises if we leaked it
        fcntl.flock(probe, fcntl.LOCK_UN)
    finally:
        os.close(probe)


@pytest.mark.parametrize("lock", _LOCKS)
def test_janitor_holder_excludes_both_eras(dirs: tuple[Path, Path], lock: str) -> None:
    """While the janitor holds a coordination lock, BOTH a new-code peer (control path)
    and an old-code peer (global-state path) are excluded — the transition is symmetric,
    not a one-way move that silently stops excluding the release still in the field."""
    control, gsd = dirs
    gs = _gs()
    acquire, release = _acquirers(gs)[lock]
    handle = acquire()
    assert handle is not None
    try:
        for path in (control / lock, gsd / lock):
            fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o644)
            try:
                with pytest.raises((BlockingIOError, OSError)):
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(fd)
    finally:
        release(handle)


@pytest.mark.parametrize("lock", _LOCKS)
def test_release_frees_both_paths_for_reacquire(dirs: tuple[Path, Path], lock: str) -> None:
    """Release must free every fd in the handle, or the second acquisition — the daemon's
    next cadence — would skip forever against its own stale hold."""
    # `dirs` is requested for its isolation side effect; this test needs no path from it.
    gs = _gs()
    acquire, release = _acquirers(gs)[lock]
    first = acquire()
    assert first is not None
    release(first)
    second = acquire()
    assert second is not None
    release(second)


def test_ticket_dispatch_lock_stays_in_global_state_dir(dirs: tuple[Path, Path]) -> None:
    """The ticket-dispatch lock deliberately did NOT move: no second chore owner ever
    dispatches a janitor support ticket, and control_dir()'s scope rule is AUDIENCE.
    Publishing a janitor-private lock would grow the external contract for nothing."""
    control, gsd = dirs
    gs = _gs()
    with gs.ticket_dispatch_lock() as held:
        assert held is True
        assert (gsd / "ticket-dispatch.lock").is_file()
        assert not (control / "ticket-dispatch.lock").exists()


@pytest.mark.parametrize("lock", _LOCKS)
def test_coincident_dirs_do_not_self_deadlock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lock: str
) -> None:
    """When control_dir() and global_state_dir() resolve to the SAME file, the lock must
    still be acquirable. Opening one inode twice denies us our own lock — flock(2)
    conflicts across independent open file descriptions even within one process — so a
    naive dual-hold turns "both paths coincide" into "this chore never runs again", and it
    looks exactly like ordinary contention in the logs. Caught by the daemon integration
    harness, which pins both env vars at one dir.
    """
    both = tmp_path / "same"
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(both))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(both))
    if "global_state" in sys.modules:
        del sys.modules["global_state"]
    gs = _gs()
    acquire, release = _acquirers(gs)[lock]
    handle = acquire()
    assert handle is not None, "coincident control/state dirs must not self-deadlock"
    try:
        assert len(handle) == 1, "one inode must be locked exactly once"
    finally:
        release(handle)
    # And it is a REAL lock, not a silent no-op: re-acquire must work after release.
    again = acquire()
    assert again is not None
    release(again)


def test_control_dir_override_redirects_the_locks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`JANITOR_CONTROL_DIR` (tests only) must move the locks with it. Without this the
    suite would contend on the real machine's control plane — a live daemon's marketplace
    refresh and a test run would then serialise against each other for real."""
    elsewhere = tmp_path / "elsewhere"
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(elsewhere))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gsd"))
    if "global_state" in sys.modules:
        del sys.modules["global_state"]
    gs = _gs()
    handle = gs.acquire_marketplace_lock()
    assert handle is not None
    try:
        assert (elsewhere / "marketplace-op.lock").is_file()
    finally:
        gs.release_marketplace_lock(handle)
