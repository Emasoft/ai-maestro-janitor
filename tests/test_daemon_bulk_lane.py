"""Background bulk lane (oauth-rotation starvation incident, 2026-07-17).

Root cause pinned here: two back-to-back ~1190 s low-priority marketplace-refresh
runs blocked the single-threaded daemon loop, starving the 60 s oauth-rotator-tick
for 20 min of every 40 — an account hit its 5 h wall inside such a blind window and
the user had to switch accounts by hand. The fix: bulk tasks run in ONE detached
child at a time (the bulk lane) so the loop's survival beats are never blocked.

Real tests, no mocks: real global-state I/O in an isolated dir, real detached
children (`daemon.py --run-task noop` — the production child-exec path with a
guaranteed-inert task name), real sleeping subprocesses for the in-flight cases.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS / "lib"))
sys.path.insert(0, str(_SCRIPTS))
daemon = importlib.import_module("daemon")

_DAEMON_PY = _SCRIPTS / "daemon.py"


@pytest.fixture()
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect global state + project dir to tmp so no real machine state is touched."""
    gsd = tmp_path / "global-state"
    gsd.mkdir()
    proj = tmp_path / "proj"
    (proj / ".janitor").mkdir(parents=True)
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(gsd))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    return gsd


def _wait_child_exit(task, timeout_s: float = 15.0) -> None:
    deadline = time.time() + timeout_s
    while task.child_alive():
        assert time.time() < deadline, "background child did not exit in time"
        time.sleep(0.05)


def _sleeping_child(seconds: float) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", f"import time; time.sleep({seconds})"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def test_run_task_child_noop_exits_zero(isolated_env: Path) -> None:
    """The production child-exec path (`--run-task noop`) works end-to-end and is inert."""
    r = subprocess.run(
        [sys.executable, str(_DAEMON_PY), "--run-task", "noop"],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, r.stderr
    assert list(isolated_env.iterdir()) == [], "noop must touch nothing"


def test_run_task_child_unknown_name_exits_nonzero(isolated_env: Path) -> None:
    """An unknown task name is a reportable failure (rc=3), never a silent success."""
    r = subprocess.run(
        [sys.executable, str(_DAEMON_PY), "--run-task", "no-such-task-xyz"],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 3


def test_spawn_and_reap_success_stamps_last_run(isolated_env: Path) -> None:
    """A reaped successful child stamps last-run (task leaves the due set) — the
    foreground bookkeeping, preserved across the detached boundary."""
    t = daemon.Task("noop", 3600, lambda: None, background=True)
    assert t.is_due()
    t.spawn_background()
    _wait_child_exit(t)
    t.poll_background()
    assert t._child is None
    # Asserted through the PUBLIC read, not a path: that is what the daemon's due-logic
    # actually calls, so it stays true across the remaining control-plane moves instead of
    # pinning today's directory (TRDD-QK7M2B0X phase B step 2 moved the stamp here).
    assert daemon.gs.read_last_run("noop") > 0
    assert (Path(os.environ["JANITOR_CONTROL_DIR"]) / "noop.last-run.ts").is_file(), \
        "the stamp must be WRITTEN to the fixed control plane a foreign reader can stat"
    assert not t.is_due()


def test_reap_failure_increments_failcount_and_stamps(isolated_env: Path) -> None:
    """A failing child (unknown name → rc=3) feeds the Pillar-1 quarantine streak AND
    stamps last-run, so a broken bulk task retries on cadence — never every loop."""
    t = daemon.Task("no-such-task-xyz", 3600, lambda: None, background=True)
    t.spawn_background()
    _wait_child_exit(t)
    t.poll_background()
    # The failcount deliberately stays in global_state_dir(): it is PRIVATE daemon state,
    # and the control-plane scope rule is AUDIENCE, not kind. The two assertions differing
    # in location is the point, not an inconsistency.
    assert int((isolated_env / "no-such-task-xyz.failcount").read_text()) == 1
    assert daemon.gs.read_last_run("no-such-task-xyz") > 0
    assert not t.is_due()


def test_in_flight_child_suppresses_due_and_sync_run(isolated_env: Path) -> None:
    """While a background child is in flight the task is never due (no double-spawn),
    never contributes 0 to the sleep (no busy-spin), and a cadence-bypass sync run()
    (the version-update consume path) is skipped instead of double-running."""
    ran = []
    t = daemon.Task("noop", 3600, lambda: ran.append(1), background=True)
    t._child = _sleeping_child(5)
    t._child_t0 = time.time()
    try:
        assert t.time_until_due() == daemon._BULK_RECHECK_SEC
        assert not t.is_due()
        t.run()
        assert ran == [], "run() must skip while the background child is in flight"
    finally:
        t._child.kill()
        t._child.wait()


def test_bulk_lane_runs_one_at_a_time(isolated_env: Path) -> None:
    """THE incident fix contract: with one bulk child running, a second due bulk task
    is deferred (stays due) — and spawns on a later pass once the lane frees."""
    # Distinct names — cadence stamps are keyed by name, so a shared name would
    # let A's reap-stamp silently satisfy B's cadence and mask the deferral.
    a = daemon.Task("noop-a", 3600, lambda: None, background=True)
    b = daemon.Task("noop-b", 3600, lambda: None, background=True)
    a._child = _sleeping_child(1.0)
    a._child_t0 = time.time()
    busy = daemon._run_due_tasks([a, b], set())
    assert busy is True
    assert b._child is None, "one bulk lane: B must be deferred while A runs"
    a._child.wait()
    daemon._run_due_tasks([a, b], set())  # reaps A (stamps), lane free → spawns B
    assert b._child is not None
    _wait_child_exit(b)
    b.poll_background()


def test_due_pass_never_blocks_on_a_bulk_child(isolated_env: Path) -> None:
    """The load-bearing property that failed on 2026-07-17: a long bulk run must not
    block the due pass. With a 5 s bulk child in flight, the pass — including a due
    FOREGROUND survival beat — completes in well under a second."""
    bulk = daemon.Task("noop", 3600, lambda: None, background=True)
    bulk._child = _sleeping_child(5)
    bulk._child_t0 = time.time()
    beats = []
    tick = daemon.Task("oauth-rotator-tick", 60, lambda: beats.append(1))
    try:
        t0 = time.time()
        daemon._run_due_tasks([bulk, tick], set())
        assert time.time() - t0 < 1.0, "due pass blocked behind the bulk child"
        assert beats == [1], "the survival beat must run while the bulk child is in flight"
    finally:
        bulk._child.kill()
        bulk._child.wait()


def test_sleep_contribution_of_lane_deferred_task_is_recheck_not_zero(
    isolated_env: Path,
) -> None:
    """A due-but-lane-deferred bulk task must not clamp the loop sleep to 1 s — that
    would busy-spin the daemon for the whole ~20 min bulk run."""
    t = daemon.Task("noop", 3600, lambda: None, background=True)
    assert t.is_due()
    assert daemon._sleep_seconds([t], set(), bulk_busy=True) == daemon._BULK_RECHECK_SEC
    assert daemon._sleep_seconds([t], set(), bulk_busy=False) == 1  # lane free → run now

def test_build_tasks_background_split_pins_the_survival_beats_foreground() -> None:
    """The bulk set is exactly the long sweeps; the survival beats (oauth tick above
    all) must NEVER be background — backgrounding them would reintroduce unbounded
    rotation latency through spawn overhead + lane contention."""
    tasks = {t.name: t.background for t in daemon._build_tasks()}
    assert {n for n, bg in tasks.items() if bg} == {
        "marketplace-refresh", "user-plugins-update", "version-update",
        "github-config-audit",
    }
    assert tasks["oauth-rotator-tick"] is False
    assert tasks["fleet-stop"] is False
    assert tasks["session-liveness"] is False
