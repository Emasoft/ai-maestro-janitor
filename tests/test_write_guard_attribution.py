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


def test_a_daemon_APPEARING_midrun_without_a_start_time_is_not_proof() -> None:
    """Half of the old `test_daemon_appearing_or_vanishing_midrun_is_not_proof`.

    The VANISHING half was split out and reversed — see
    `test_a_daemon_that_EXITED_during_the_run_is_still_credited`. Appearing with no
    `started_at` stays False because a wedged daemon produces the identical shape."""
    assert daemon_ticked(None, (4242, 1_060)) is False


def test_a_RESPAWNED_daemon_still_counts_when_the_heartbeat_advanced() -> None:
    """Reversed 2026-07-21. This used to assert False on the reasoning "a restarted daemon is
    not the process we witnessed".

    That was wrong about how the janitor actually behaves: it respawns its own daemon
    routinely — self-update after a release, `daemon_needs_restart` on a stale version, the
    wedged-daemon kill inside `ensure_daemon_running`. So the pid changes most often on a
    RELEASE DAY, which made the full suite exit non-zero exactly when `publish.py`'s test gate
    ran it. A guard that fires because the system is working normally trains people to ignore
    it, and it blocked a release the day this was found.

    Both ends still have to show a LIVE pid (`_daemon_witness` checks liveness) and the
    heartbeat still has to ADVANCE, which together already prove a daemon ran and wrote across
    the window. Which numeric pid did it is not part of that proof."""
    assert daemon_ticked((4242, 1_000), (9999, 1_060)) is True


def test_a_daemon_that_CAME_UP_during_the_run_is_credited_when_it_beat_after_the_start() -> None:
    """The other edge of the same release-day respawn.

    If the suite snapshots in the gap between the old daemon exiting for a self-update and
    the replacement writing its pid, `before` is None — yet a daemon was running and writing
    for most of the window. `started_at` is what makes that decidable: a heartbeat at or
    after the moment the window opened can only come from a daemon that was alive during it.
    """
    started = 1_000
    assert daemon_ticked(None, (9999, 1_050), started_at=started) is True


def test_a_WEDGED_daemon_is_still_refused_even_with_a_start_time() -> None:
    """The negative that `started_at` must not destroy.

    A stale pid file whose process is alive but frozen also produces `before=None,
    after=(pid, beat)` — the shape above. The difference is that its heartbeat predates the
    run, because it has not moved in hours. If this were credited, any test could leak into
    the real state dir and hide behind a daemon that never wrote anything."""
    started = 1_000
    assert daemon_ticked(None, (9999, 940), started_at=started) is False


def test_without_a_start_time_an_absent_before_is_still_refused() -> None:
    """No clock, no credit. `started_at` is optional, and when it is missing the two cases
    above are indistinguishable — so the answer stays the conservative one."""
    assert daemon_ticked(None, (9999, 1_050)) is False


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


def test_a_daemon_that_EXITED_during_the_run_is_still_credited() -> None:
    """Since v0.59.0 this is a FIRST-CLASS event, not an anomaly.

    The daemon deliberately exits the moment an ai-maestro server claims the host
    (ARCHITECTURE §7.2, one-daemon-per-host). The first time a real server came up it did
    exactly that mid-suite — and the guard then blamed the departed daemon's earlier writes
    on the tests, failing publish.py's own gate with all 13430 tests passing.

    A daemon witnessed ALIVE at the start wrote whatever it wrote before leaving; that its
    pid is gone by the end says nothing about who made those writes."""
    assert daemon_ticked((4242, 1_000), None) is True


def test_no_daemon_at_EITHER_end_is_still_a_real_leak_even_with_a_start_time() -> None:
    """The negative the exit case must not swallow. `test_no_daemon_at_all_is_never_proof`
    covers the plain form; this pins that supplying `started_at` does not soften it —
    nothing was running to credit, so any mutation is exactly what the guard exists for."""
    assert daemon_ticked(None, None, started_at=1_000) is False
