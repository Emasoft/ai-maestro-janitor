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
