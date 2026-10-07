"""Per-beat foreground budget (TRDD-QJ5LP4W2) — a run of long-but-individually-legal
foreground task bodies must not silently starve a survival beat for a whole pass.

Root cause pinned on 8BXMNQ4T: 12 stalls in a 6h22m log snapshot, median 92.7% of
each stall window filled by cumulative foreground task bodies (not a single long
one — one stall was 55s+15s). The fix: track cumulative foreground runtime per pass
and defer non-floor tasks once it exceeds a budget, while floor tasks (the OAuth
survival chain) always run and non-floor dispatch order is oldest-last-run-first
(mirroring `_next_bulk_task`'s own starvation fix) instead of fixed list position.

Real tests: real `daemon.Task` objects with a controlled-duration `fn`, real
global-state + log I/O in an isolated tmp dir (isolated_env fixture pattern shared
with test_daemon_bulk_lane.py / test_chore_coordination.py). No mocking of the code
under test; `_FOREGROUND_BUDGET_SEC` is monkeypatched (the module-level default is
computed once at import time from an env var, so a per-test env var cannot change it
after the fact) and task duration is real wall-clock sleep — `Task.run()` truncates
its measured duration to whole seconds (`int(time.time() - t0)`), so a task meant to
consume the budget sleeps past 1s rather than a few ms.
"""

from __future__ import annotations

import importlib
import sys
import time
from pathlib import Path
from typing import Any, Iterator

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_ROOT / "scripts"))
daemon = importlib.import_module("daemon")
state = importlib.import_module("state")


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Isolated global state + log dir, with the process-lifetime path caches
    flushed both sides (test_chore_coordination.py's pattern) — log_dir()/
    janitor_root() are @lru_cache(maxsize=1) and would otherwise keep whichever
    tmp_path an earlier test in this pytest process happened to resolve first."""
    gsd = tmp_path / "global-state"
    gsd.mkdir()
    proj = tmp_path / "proj"
    (proj / ".janitor").mkdir(parents=True)
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(gsd))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    for fn in (state.project_root, state.janitor_root, state.state_dir, state.log_dir):
        fn.cache_clear()
    yield gsd
    for fn in (state.project_root, state.janitor_root, state.state_dir, state.log_dir):
        fn.cache_clear()


def _stamp_last_run(task: Any, ts: int) -> None:
    state.atomic_write(task.last_run_path, str(ts))


def _slow_task(name: str, seconds: float) -> Any:
    return daemon.Task(name, 0, lambda: time.sleep(seconds))


def test_floor_task_runs_even_after_budget_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    """oauth-rotator-tick must fire even when an earlier body already blew the budget."""
    monkeypatch.setattr(daemon, "_FOREGROUND_BUDGET_SEC", 1)
    hog = _slow_task("cold-cache-clear", 1.2)
    tick = _slow_task("oauth-rotator-tick", 0.01)
    daemon._run_due_tasks([hog, tick], yielded=set())
    assert tick._last_run() > 0, "floor task must run despite an exhausted budget"


def test_floor_task_dispatches_before_older_non_floor_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The floor task must be DISPATCHED before the hog, not merely run at some
    point — an age-only sort (the regression this guards) would place a floor task
    dispatched *after* a non-floor task with an older last-run, so the survival
    beat would wait behind the hog's whole body instead of the reverse. Stamps are
    whole seconds and cannot prove dispatch order (both tasks could tie or the hog
    could still finish first in real time); only the daemon.log START-line offsets
    can. The hog's last-run is stamped far OLDER than the tick's so an age-only
    sort would dispatch the hog first — proving this test would catch the bug the
    fix repairs, not just repeat the fix's own tie-breaking."""
    monkeypatch.setattr(daemon, "_FOREGROUND_BUDGET_SEC", 100)
    now = int(time.time())
    hog = _slow_task("cold-cache-clear", 0.05)
    tick = _slow_task("oauth-rotator-tick", 0.05)
    _stamp_last_run(hog, now - 1000)  # far older — an age-only sort runs this first
    _stamp_last_run(tick, now)  # fresh — an age-only sort would defer/run this last
    daemon._run_due_tasks([hog, tick], yielded=set())
    log_text = (state.log_dir() / "daemon.log").read_text()
    tick_start = log_text.index("task 'oauth-rotator-tick' starting")
    hog_start = log_text.index("task 'cold-cache-clear' starting")
    assert tick_start < hog_start, "floor task must be dispatched before an older non-floor task"


def test_deferrable_task_past_budget_is_skipped_and_stays_due(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-floor task past the budget is skipped this pass; last-run is untouched
    and the task remains due for the next pass (never silently dropped)."""
    monkeypatch.setattr(daemon, "_FOREGROUND_BUDGET_SEC", 1)
    hog = _slow_task("cold-cache-clear", 1.2)
    other = _slow_task("gh-notify-inbox", 0.01)
    daemon._run_due_tasks([hog, other], yielded=set())
    assert other._last_run() == 0, "deferred task must not stamp last-run"
    assert other.is_due(), "deferred task must stay due for the next pass"


def test_transition_log_line_appears_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """One 'chore-coordination: foreground budget exceeded' line per pass, not once
    per deferred task."""
    monkeypatch.setattr(daemon, "_FOREGROUND_BUDGET_SEC", 1)
    hog = _slow_task("cold-cache-clear", 1.2)
    a = _slow_task("gh-notify-inbox", 0.01)
    b = _slow_task("integrity-repin", 0.01)
    daemon._run_due_tasks([hog, a, b], yielded=set())
    log_text = (state.log_dir() / "daemon.log").read_text()
    assert log_text.count("chore-coordination: foreground budget") == 1


def test_non_floor_dispatch_is_oldest_last_run_first_not_list_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Once budget is exhausted, WHICH non-floor task got to run before the cutoff
    must be decided by oldest-last-run-first (mirroring `_next_bulk_task`), not by
    position in the fixed registration list. List order here is deliberately
    [newest, mid, oldest] — the reverse of dispatch priority — so a pass-by-position
    implementation would run `newest` and this test would fail."""
    monkeypatch.setattr(daemon, "_FOREGROUND_BUDGET_SEC", 1)
    now = int(time.time())
    newest = _slow_task("gh-notify-inbox", 1.2)
    mid = _slow_task("integrity-repin", 1.2)
    oldest = _slow_task("cold-cache-clear", 1.2)
    _stamp_last_run(newest, now)
    _stamp_last_run(mid, now - 100)
    _stamp_last_run(oldest, now - 1000)
    # Sabotage due-ness for the two the budget must NOT let run: interval 0 means
    # is_due() only cares whether the child is alive, so all three stay due despite
    # the fresh stamps above.
    daemon._run_due_tasks([newest, mid, oldest], yielded=set())
    assert oldest._last_run() > now - 1000, "the oldest-last-run task must run first"
    assert newest._last_run() == now, "newer non-floor tasks must be deferred, not run"
    assert mid._last_run() == now - 100, "newer non-floor tasks must be deferred, not run"


def test_zero_budget_defers_every_non_floor_task_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """budget_used (0.0) >= a 0 budget is True before anything has run, so a 0 budget
    defers every non-floor task on every pass — the documented reason the module
    default clamps to max(1, ...) rather than letting an env override reach 0.
    A 0 budget is unreachable through the module default (`_env_interval` itself
    has no floor; `max(1, ...)` is the only clamp), which is exactly why this test
    monkeypatches past it — it deliberately exercises the unclamped state the
    module-level default never produces."""
    monkeypatch.setattr(daemon, "_FOREGROUND_BUDGET_SEC", 0)
    a = _slow_task("gh-notify-inbox", 0.01)
    tick = _slow_task("oauth-rotator-tick", 0.01)
    daemon._run_due_tasks([a, tick], yielded=set())
    assert a._last_run() == 0, "non-floor task must be deferred even before any run"
    assert tick._last_run() > 0, "floor task is unaffected by a 0 budget"



# --- overrun watch (card 6CF3L7IJ): record a budget overrun WHILE the body still runs ---


def _log_text() -> str:
    p = state.log_dir() / "daemon.log"
    return p.read_text() if p.exists() else ""


def _wait_for(pred: Any, deadline_s: float = 10.0) -> bool:
    """Poll, never sleep a fixed time: the assertion must hold on a loaded host."""
    end = time.time() + deadline_s
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


@pytest.fixture
def overrun_watch(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    monkeypatch.setattr(daemon, "_FOREGROUND_BUDGET_SEC", 0.2)
    monkeypatch.setattr(daemon, "_OVERRUN_WATCH_INTERVAL_S", 0.05)
    watch = daemon._OverrunWatchThread()
    watch.start()
    yield watch
    watch.shutdown(5)
    daemon._overrun_runs.clear()


def test_overrun_line_and_stamp_appear_before_body_returns(overrun_watch: Any, isolated_env: Path) -> None:
    """The 'still running' line and the stamp exist while the body is still inside fn()."""
    seen: dict[str, Any] = {}

    def body() -> None:
        stamp = isolated_env / "task-overrun.slow-one.ts"
        seen["ok"] = _wait_for(lambda: "task 'slow-one' still running" in _log_text() and stamp.exists())
        seen["stamp"] = stamp.read_text() if stamp.exists() else ""
        time.sleep(0.4)  # extra wakes: the line must still appear only once
        seen["done_logged"] = "task 'slow-one' done" in _log_text()

    daemon.Task("slow-one", 0, body).run()
    assert seen["ok"], "line and stamp must exist before the body returns"
    assert not seen["done_logged"]
    pid, name, start = seen["stamp"].split(" ")
    assert (int(pid), name) == (__import__("os").getpid(), "slow-one") and int(start) > 0
    assert _log_text().count("task 'slow-one' still running") == 1
    assert "(budget 0.2s)" in _log_text()
    assert not (isolated_env / "task-overrun.slow-one.ts").exists(), "stamp removed after the run"


def test_fast_task_produces_no_overrun_line_or_stamp(overrun_watch: Any, isolated_env: Path) -> None:
    """A body under budget leaves neither a line nor a stamp."""
    daemon.Task("quick", 0, lambda: time.sleep(0.01)).run()
    time.sleep(0.2)  # negative assertion: give the watch several wakes to (wrongly) fire
    assert "still running" not in _log_text()
    assert not list(isolated_env.glob("task-overrun.*"))


def test_raising_body_still_clears_registration(overrun_watch: Any) -> None:
    """An exception in the body must not leave the run registered."""

    def boom() -> None:
        raise RuntimeError("x")

    daemon.Task("boomer", 0, boom).run()
    assert daemon._overrun_runs == {}


def test_own_thread_task_is_covered(overrun_watch: Any) -> None:
    """A Task.run on another thread (the rotator tick's shape) is reported too."""
    import threading

    t = threading.Thread(
        target=daemon.Task("oauth-rotator-tick", 0, lambda: time.sleep(0.6), own_thread=True).run
    )
    t.start()
    assert _wait_for(lambda: "task 'oauth-rotator-tick' still running" in _log_text())
    t.join()


def test_bulk_task_produces_no_overrun_line(overrun_watch: Any) -> None:
    """The bulk child path calls task.fn(), never Task.run, so nothing is registered."""
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(daemon._run_task_child)))
    called = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "fn" in called and "run" not in called
    assert daemon._run_task_child("noop-overrun-bulk") == 0
    time.sleep(0.2)
    assert daemon._overrun_runs == {}
    assert "still running" not in _log_text()


def test_watch_thread_survives_a_failing_pass(
    overrun_watch: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One exception inside a pass is logged once and the thread keeps watching."""
    real = daemon._overrun_stamp_path
    calls = {"n": 0}

    def flaky(name: str) -> Path:
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("boom")
        return real(name)

    monkeypatch.setattr(daemon, "_overrun_stamp_path", flaky)
    daemon.Task("flaky-run", 0, lambda: _wait_for(lambda: "task 'flaky-run' still running" in _log_text())).run()
    assert "overrun-watch: pass failed" in _log_text()
    assert _log_text().count("overrun-watch: pass failed") == 1
    assert "task 'flaky-run' still running" in _log_text()
    assert overrun_watch.is_alive()


def test_start_sweep_removes_stamp_with_dead_pid_keeps_own(isolated_env: Path) -> None:
    """A stamp from a previous daemon (dead pid) is removed at start; this daemon's stays."""
    import os

    dead = isolated_env / "task-overrun.old.ts"
    mine = isolated_env / "task-overrun.mine.ts"
    dead.write_text("999999 old 1700000000")
    mine.write_text(f"{os.getpid()} mine 1700000000")
    daemon._overrun_sweep_stale()
    assert not dead.exists()
    assert mine.exists()


def test_elapsed_comes_from_monotonic_not_wall_clock(overrun_watch: Any) -> None:
    """A wall clock far in the past or future must not change the logged elapsed figure."""
    import threading

    for wall_skew, name in ((-40000, "wake"), (+1_000_000, "backstep")):
        done = threading.Event()
        mono = time.monotonic() - 3  # fresh per run, so the elapsed figure stays at 3s

        def reg(n: str = name, skew: int = wall_skew, m: float = mono) -> None:
            daemon._overrun_register(n, time.time() + skew, m)
            done.wait(10)
            daemon._overrun_clear(n)

        th = threading.Thread(target=reg)
        th.start()
        try:
            assert _wait_for(lambda n=name: f"task '{n}' still running after 3s" in _log_text())  # type: ignore[misc]
        finally:
            done.set()
            th.join(5)
    assert "40000s" not in _log_text()
    assert daemon._overrun_runs == {}


def test_stalled_stamp_write_does_not_block_another_task_exit(
    overrun_watch: Any, isolated_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """While the watch is stuck writing a stamp, a Task.run on another thread still returns."""
    import threading

    entered = threading.Event()
    release = threading.Event()
    real = state.atomic_write

    def slow(path: Any, text: str, *a: Any, **k: Any) -> Any:
        if "task-overrun." in str(path):
            entered.set()
            release.wait(10)  # the test releases this in its finally; bounded anyway
        return real(path, text, *a, **k)

    monkeypatch.setattr(state, "atomic_write", slow)
    first = threading.Thread(target=daemon.Task("stall-a", 0, lambda: release.wait(10)).run)
    second_done = threading.Event()
    second = threading.Thread(
        target=lambda: (daemon.Task("stall-b", 0, lambda: None).run(), second_done.set())
    )
    first.start()
    try:
        assert entered.wait(10), "watch must reach the (blocked) stamp write"
        second.start()
        assert second_done.wait(5), "a task exit must not wait behind the watch's disk write"
    finally:
        release.set()
        first.join(5)
        second.join(5)
    assert _wait_for(lambda: not list(isolated_env.glob("task-overrun.*")))

def test_failing_stamp_write_still_logs_every_over_budget_run(
    overrun_watch: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stamp write that raises OSError must not hide the 'still running' line of any run."""
    import threading

    real = state.atomic_write

    def failing(path: Any, text: str, *a: Any, **k: Any) -> Any:
        if "task-overrun." in str(path):
            raise OSError("no space left")
        return real(path, text, *a, **k)

    monkeypatch.setattr(state, "atomic_write", failing)
    release = threading.Event()
    threads = [
        threading.Thread(target=daemon.Task(n, 0, lambda: release.wait(10)).run)
        for n in ("wfail-a", "wfail-b")
    ]
    for t in threads:
        t.start()
    try:
        assert _wait_for(
            lambda: all(f"task '{n}' still running" in _log_text() for n in ("wfail-a", "wfail-b"))
        ), "both over-budget runs must be logged although the stamp write fails"
        time.sleep(0.3)  # several more passes: the write failure must not be logged again
        for n in ("wfail-a", "wfail-b"):
            assert _log_text().count(f"stamp write failed for '{n}'") == 1
    finally:
        release.set()
        for t in threads:
            t.join(5)
    assert "overrun-watch: pass failed" not in _log_text()
