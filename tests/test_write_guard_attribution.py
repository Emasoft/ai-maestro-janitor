"""The write-guard's daemon attribution must not become a hole (S1f).

WHY: the guard failed the whole suite because the LIVE janitor daemon wrote its own state
dir mid-run — work it is supposed to do. The obvious fix (exclude those filenames) is the
SAME mistake that made an earlier guard blind to the real 2026-07-11 clobber: it excluded
`.log` and `.restage-stamp` as "daemon noise", and those were exactly the two files the
incident wrote.

So a mutation is credited to the daemon only on PROOF it was ticking. These tests pin that
proof, because every weakening of it re-opens a way for a real test leak to hide behind a
daemon that was not actually running.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from conftest import _daemon_witness, daemon_ticked


def test_same_pid_with_advancing_heartbeat_is_proof() -> None:
    """The ONLY accepted signal: one daemon, alive throughout, heartbeat moving."""
    assert daemon_ticked((4242, 1_000), (4242, 1_060)) is True


def test_no_daemon_at_all_is_never_proof() -> None:
    """No daemon ⇒ nothing can be credited with the write ⇒ it must fail as a test leak."""
    assert daemon_ticked(None, None) is False


def test_daemon_appearing_or_vanishing_midrun_is_not_proof() -> None:
    """A daemon that only existed at one end did not demonstrably write across the run."""
    assert daemon_ticked(None, (4242, 1_060)) is False
    assert daemon_ticked((4242, 1_000), None) is False


def test_a_different_pid_is_not_proof() -> None:
    """A restarted/replaced daemon is not the process we witnessed — do not credit it."""
    assert daemon_ticked((4242, 1_000), (9999, 1_060)) is False


def test_frozen_heartbeat_is_not_proof() -> None:
    """THE important negative. A stale pid file or a wedged daemon leaves a live-looking pid
    with a heartbeat that never moves. If that counted as proof, any test could leak into the
    global state dir and be excused by a daemon that was writing nothing at all."""
    assert daemon_ticked((4242, 1_000), (4242, 1_000)) is False
    assert daemon_ticked((4242, 1_000), (4242, 999)) is False  # clock went backwards


def test_witness_reads_a_live_daemon_from_disk(tmp_path: Path) -> None:
    """_daemon_witness reads pid+heartbeat and confirms liveness. Uses THIS process's pid —
    guaranteed alive, and no signal is actually delivered (signal 0 is a liveness probe)."""
    gsd = tmp_path / "gs"
    gsd.mkdir()
    (gsd / "daemon.pid").write_text(str(os.getpid()), encoding="utf-8")
    (gsd / "daemon.heartbeat.ts").write_text("1700000000", encoding="utf-8")

    assert _daemon_witness(gsd) == (os.getpid(), 1700000000)


def test_witness_ignores_a_dead_pid(tmp_path: Path) -> None:
    """A pid file left behind by a dead daemon must NOT be witnessed as live — otherwise a
    stale file on disk would silently license writes to the guarded dir forever."""
    gsd = tmp_path / "gs"
    gsd.mkdir()
    # Run a real process to completion so its pid is GENUINELY dead and reaped — never guess
    # an "unused" pid, which the OS is free to recycle into a live process mid-test.
    # (subprocess.run, not os.fork: forking a multi-threaded pytest is deprecated and noisy.)
    proc = subprocess.Popen([sys.executable, "-c", "pass"])  # noqa: S603 -- fixed argv
    proc.wait()  # reaped: the pid is now genuinely gone, not merely a zombie
    pid = proc.pid

    (gsd / "daemon.pid").write_text(str(pid), encoding="utf-8")
    (gsd / "daemon.heartbeat.ts").write_text("1700000000", encoding="utf-8")

    assert _daemon_witness(gsd) is None


def test_witness_survives_missing_and_garbage_state(tmp_path: Path) -> None:
    """Absent or corrupt state must read as 'no daemon' (⇒ mutations fail as leaks), never
    raise — a crashing guard in sessionfinish would take the whole suite's verdict with it."""
    assert _daemon_witness(tmp_path / "nonexistent") is None

    gsd = tmp_path / "gs"
    gsd.mkdir()
    (gsd / "daemon.pid").write_text("not-a-pid", encoding="utf-8")
    (gsd / "daemon.heartbeat.ts").write_text("nonsense", encoding="utf-8")
    assert _daemon_witness(gsd) is None
