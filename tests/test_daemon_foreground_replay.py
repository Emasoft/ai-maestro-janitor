"""Replay harness for the WORST measured foreground-occupancy pattern (TRDD-9FONCK33),
closing acceptance box 3 of TRDD-QJ5LP4W2 (per-beat foreground budget, landed 5f7f3dba
/ 57a7f267): "A test pins the bound, and `oauth-rotator-tick` is shown still firing on
cadence with the worst measured occupancy pattern replayed."

⚠ THE OCCUPANCY PATTERN IS A PARAMETER, NOT A CONSTANT (QJ5LP4W2's own annotation).
`read_worst_pass_pattern()` below reads it, at run time, from whichever daemon.log
window is available — never a hard-coded duration such as the 78s/102s/137s/191s
values 8BXMNQ4T happened to measure on one snapshot. A maximum is an order statistic;
pinning it as a constant would be stale the moment a wider window finds something
larger.

Pass-boundary rule (an INFERENCE from observed timing, not a documented log
contract — daemon.log carries no explicit pass marker): a foreground `starting` line
begins a NEW pass when the gap since the previous foreground `done`/`FAILED` line is
>= _PASS_GAP_SEC (10s). Measured on the real host log
(~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/global-state/daemon.log):
consecutive task lines inside one `_run_due_tasks` pass are <=2s apart (dispatch is
synchronous, back-to-back); the gap between passes (the main loop's sleep) is ~30-60s.
10s sits comfortably between the two and is documented here as exactly that inference,
not a guarantee.

Background (bulk-lane) task bodies — any line whose text contains "(background" — are
excluded entirely: they run in a detached child and never count toward the foreground
budget (`_FOREGROUND_BUDGET_SEC` / `budget_used` in `_run_due_tasks`), so folding them
into the "worst pass" would measure the wrong thing.

Pointing the harness at a different log window:

    JANITOR_REPLAY_LOG=/path/to/daemon.log JANITOR_REPLAY_SCALE=0.01 \\
        uv run pytest -q tests/test_daemon_foreground_replay.py

`JANITOR_REPLAY_LOG` unset falls back to the real host daemon.log
(~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/global-state/daemon.log);
if that is unreadable too, the real-log test SKIPS (naming why) rather than failing —
the synthetic-log test below always runs and proves the same mechanism regardless.
`JANITOR_REPLAY_SCALE` (default 0.01) scales every measured duration AND the real
`_FOREGROUND_BUDGET_SEC` by the same factor, so a 191s body replays as ~1.9s while
preserving the ratios the bound depends on.

Real tests: real `daemon.Task` objects with `time.sleep(scaled_seconds)` bodies (no
mocks), driven through the real `_run_due_tasks`, in the same isolated_env fixture
pattern as test_daemon_foreground_budget.py.
"""

from __future__ import annotations

import importlib
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_ROOT / "scripts"))
daemon = importlib.import_module("daemon")
state = importlib.import_module("state")

_PASS_GAP_SEC = 10  # see module docstring — an inference from observed log timing

_LINE_RE = re.compile(
    r"^\[(?P<ts>[^\]]+)\]\s+(?:\[s:[0-9a-f]+\]\s+)?task '(?P<name>[^']+)' (?P<rest>.*)$"
)
_DONE_RE = re.compile(r"(?:done|FAILED) in (\d+)s")

_DEFAULT_HOST_LOG = (
    Path.home() / ".claude" / "plugins" / "data" / "ai-maestro-janitor-ai-maestro-plugins"
    / "global-state" / "daemon.log"
)

# A small, committed stand-in for the real host log's worst measured pass (real
# durations observed 2026-09-05, before the QJ5LP4W2 fix landed): session-liveness
# and cold-cache-clear stacked ahead of gh-notify-inbox and oauth-rotator-tick, plus
# an earlier, smaller, unrelated pass that the >=10s gap must correctly exclude.
_SYNTHETIC_WORST_PASS_LOG = (
    "[2026-01-01T00:00:00+0000] task 'gh-notify-inbox' starting\n"
    "[2026-01-01T00:00:05+0000] task 'gh-notify-inbox' done in 5s\n"
    "[2026-01-01T00:05:00+0000] task 'session-liveness' starting\n"
    "[2026-01-01T00:07:46+0000] task 'session-liveness' done in 166s\n"
    "[2026-01-01T00:07:46+0000] task 'cold-cache-clear' starting\n"
    "[2026-01-01T00:09:11+0000] task 'cold-cache-clear' done in 85s\n"
    "[2026-01-01T00:09:11+0000] task 'gh-notify-inbox' starting\n"
    "[2026-01-01T00:09:32+0000] task 'gh-notify-inbox' done in 21s\n"
    "[2026-01-01T00:09:33+0000] task 'oauth-rotator-tick' starting\n"
    "[2026-01-01T00:09:35+0000] task 'oauth-rotator-tick' done in 2s\n"
)


@dataclass(frozen=True)
class ReplayPattern:
    """The worst-measured-occupancy pass: foreground task bodies (name, seconds), in
    dispatch order, deduped to each name's first occurrence within that pass, plus the
    ISO timestamps bounding the pass (first `starting`, last `done`/`FAILED`)."""

    bodies: tuple[tuple[str, int], ...]
    window_start: str
    window_end: str
    total_seconds: int


def _parse_ts(ts_raw: str) -> datetime:
    return datetime.fromisoformat(ts_raw)


def read_worst_pass_pattern(log_text: str) -> ReplayPattern:
    """Read the worst measured per-pass foreground occupancy pattern from `log_text`.

    Fails fast (raises ValueError) on a log with no parseable foreground task-body
    pairs — it must never invent a pattern. Background bodies ("(background" in the
    line) are excluded; see the module docstring for why and for the pass-boundary
    rule."""
    pending_start: dict[str, tuple[str, datetime]] = {}
    current_pass: list[tuple[str, int, str, str]] = []
    passes: list[list[tuple[str, int, str, str]]] = []
    last_end_dt: datetime | None = None
    for line in log_text.splitlines():
        m = _LINE_RE.match(line)
        if not m:
            continue
        ts_raw, name, rest = m.group("ts"), m.group("name"), m.group("rest")
        if "(background" in rest:
            continue
        dt = _parse_ts(ts_raw)
        if rest == "starting":
            if last_end_dt is not None and (dt - last_end_dt).total_seconds() >= _PASS_GAP_SEC:
                if current_pass:
                    passes.append(current_pass)
                current_pass = []
            pending_start[name] = (ts_raw, dt)
            continue
        dm = _DONE_RE.match(rest)
        if not dm:
            continue
        secs = int(dm.group(1))
        start_ts, _start_dt = pending_start.pop(name, (ts_raw, dt))
        current_pass.append((name, secs, start_ts, ts_raw))
        last_end_dt = dt
    if current_pass:
        passes.append(current_pass)
    if not passes:
        raise ValueError(
            "no foreground task-body pairs (\"task '<n>' starting\" + "
            "\"done in Ns\"/\"FAILED in Ns\", excluding \"(background\" lines) "
            "found in log text — refusing to invent a pattern"
        )
    worst = max(passes, key=lambda p: sum(secs for _, secs, _, _ in p))
    seen: set[str] = set()
    bodies: list[tuple[str, int]] = []
    for name, secs, _start_ts, _end_ts in worst:
        if name in seen:
            continue
        seen.add(name)
        bodies.append((name, secs))
    return ReplayPattern(
        bodies=tuple(bodies),
        window_start=worst[0][2],
        window_end=worst[-1][3],
        total_seconds=sum(secs for _, secs in bodies),
    )


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Isolated global state + log dir (test_daemon_foreground_budget.py's pattern) —
    log_dir()/janitor_root() are @lru_cache(maxsize=1) and would otherwise keep
    whichever tmp_path an earlier test in this pytest process resolved first."""
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


def _sleep_fn(seconds: float) -> Any:
    return lambda: time.sleep(seconds)


def _build_replay_tasks(
    pattern: ReplayPattern, scale: float
) -> tuple[list[Any], float, float, float, list[tuple[str, int]]]:
    """Wire real daemon.Task objects for every body in the winning pass, scaled by
    `scale`. A floor name already present in the pattern keeps its MEASURED body (it
    is never dropped/replaced); `oauth-rotator-tick` is appended with a nominal 1s
    body only when the pass genuinely never dispatched it. Every task's last-run is
    stamped deterministically, oldest-first in the pass's own chronological order, so
    `_run_due_tasks`' oldest-last-run-first tie-break reproduces the measured dispatch
    order instead of an arbitrary one.

    Returns (tasks, scaled_budget, floor_sum_scaled, max_nonfloor_scaled, bodies) —
    `bodies` is the final (name, seconds) list, in the same order the last-run stamps
    were assigned, so the caller can predict dispatch order without re-deriving it."""
    bodies = list(pattern.bodies)
    if not any(name == "oauth-rotator-tick" for name, _ in bodies):
        bodies.append(("oauth-rotator-tick", 1))
    now = int(time.time())
    tasks: list[Any] = []
    floor_sum = 0.0
    max_nonfloor = 0.0
    for i, (name, secs) in enumerate(bodies):
        scaled = secs * scale
        task = daemon.Task(name, 0, _sleep_fn(scaled))
        _stamp_last_run(task, now - (len(bodies) - i) * 1000)
        tasks.append(task)
        if name in daemon._FOREGROUND_FLOOR:
            floor_sum += scaled
        else:
            max_nonfloor = max(max_nonfloor, scaled)
    scaled_budget = daemon._FOREGROUND_BUDGET_SEC * scale
    return tasks, scaled_budget, floor_sum, max_nonfloor, bodies


def _predict_dispatch(
    bodies: list[tuple[str, int]], scale: float, scaled_budget: float
) -> tuple[list[str], list[str]]:
    """Simulate `_run_due_tasks`' own dispatch loop over `bodies` (stamped
    oldest-first in this exact order by `_build_replay_tasks`, so its floor-first/
    oldest-last-run-first sort reduces to: every floor body first in `bodies` order,
    then every non-floor body in `bodies` order) to predict which bodies START and
    which are DEFERRED. Mirrors the real budget check exactly: a floor body always
    runs; a non-floor body is deferred once `budget_used >= scaled_budget` and every
    non-floor body is checked in order, so deferral is a suffix once it begins."""
    floor_order = [(n, s) for n, s in bodies if n in daemon._FOREGROUND_FLOOR]
    nonfloor_order = [(n, s) for n, s in bodies if n not in daemon._FOREGROUND_FLOOR]
    started: list[str] = []
    deferred: list[str] = []
    budget_used = 0.0
    for name, secs in floor_order + nonfloor_order:
        is_floor = name in daemon._FOREGROUND_FLOOR
        if not is_floor and budget_used >= scaled_budget:
            deferred.append(name)
            continue
        started.append(name)
        budget_used += secs * scale
    return started, deferred


def _replay_and_assert(
    monkeypatch: pytest.MonkeyPatch, pattern: ReplayPattern, scale: float, source: str
) -> None:
    """Replay `pattern` through the real `_run_due_tasks`/`Task` machinery at `scale`
    and assert the acceptance-box-3 claims: (a) the STARTED/DEFERRED split predicted
    from the stamped dispatch order matches daemon.log exactly (catches a broken
    deferral that a looser "tick precedes whichever ran" check would miss), (b)
    oauth-rotator-tick dispatches before every started non-floor body, (c) a
    "chore-coordination: foreground budget" line appears exactly once iff anything
    was deferred, and (d) elapsed wall time stays within `sum(scaled floor bodies) +
    scaled budget + max(scaled non-floor body)` — a floor task always runs in full,
    and at most one non-floor body is allowed to cross the budget and still run in
    full — plus scheduling slack proportional to the bound itself."""
    tasks, scaled_budget, floor_sum, max_nonfloor, bodies = _build_replay_tasks(pattern, scale)
    monkeypatch.setattr(daemon, "_FOREGROUND_BUDGET_SEC", scaled_budget)
    started, deferred = _predict_dispatch(bodies, scale, scaled_budget)

    t0 = time.time()
    daemon._run_due_tasks(tasks, yielded=set())
    elapsed = time.time() - t0

    log_text = (state.log_dir() / "daemon.log").read_text()
    ctx = (
        f"[{source}] started={started} deferred={deferred} "
        f"pattern={pattern.bodies} scale={scale} window={pattern.window_start}..{pattern.window_end}"
    )
    for name in started:
        assert f"task '{name}' starting" in log_text, f"expected '{name}' to dispatch — {ctx}"
    for name in deferred:
        assert f"task '{name}' starting" not in log_text, f"expected '{name}' to STAY deferred — {ctx}"
    if deferred:
        assert log_text.count("chore-coordination: foreground budget") == 1, (
            f"expected exactly one budget-exceeded log line — {ctx}"
        )

    tick_idx = log_text.index("task 'oauth-rotator-tick' starting")
    for name in started:
        if name == "oauth-rotator-tick" or name in daemon._FOREGROUND_FLOOR:
            continue
        idx = log_text.index(f"task '{name}' starting")
        assert tick_idx < idx, f"oauth-rotator-tick must dispatch before '{name}' — {ctx}"

    bound = floor_sum + scaled_budget + max_nonfloor
    epsilon = 0.25 + 0.10 * bound  # slack proportional to what is being measured
    assert elapsed <= bound + epsilon, (
        f"replayed pass took {elapsed:.3f}s > bound "
        f"floor_sum({floor_sum:.3f}) + budget({scaled_budget:.3f}) + "
        f"max_nonfloor({max_nonfloor:.3f}) = {bound:.3f} (+{epsilon:.3f}s slack) — {ctx}"
    )


def test_pattern_reader_picks_the_pass_with_the_larger_summed_occupancy() -> None:
    """The reader must pick the WORST pass by summed foreground occupancy, not the
    first, last, or a fixed-position one — and must exclude the earlier, smaller,
    >=10s-separated pass entirely."""
    pattern = read_worst_pass_pattern(_SYNTHETIC_WORST_PASS_LOG)
    assert [name for name, _ in pattern.bodies] == [
        "session-liveness",
        "cold-cache-clear",
        "gh-notify-inbox",
        "oauth-rotator-tick",
    ]
    assert pattern.total_seconds == 166 + 85 + 21 + 2
    assert pattern.window_start == "2026-01-01T00:05:00+0000"
    assert pattern.window_end == "2026-01-01T00:09:35+0000"


def test_pattern_reader_raises_on_log_with_no_foreground_bodies() -> None:
    """A log with no `task '<n>' starting`/`done in Ns` pairs must raise, never
    silently invent a pattern (e.g. an empty tuple treated as 'nothing ran')."""
    with pytest.raises(ValueError):
        read_worst_pass_pattern("not a daemon log\njust unrelated noise\n")
    with pytest.raises(ValueError):
        read_worst_pass_pattern("")


def test_replay_synthetic_worst_pattern_keeps_tick_within_cadence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Always runs — no host log required — proving the mechanism on a small,
    committed pattern shaped like the real host log's pre-fix worst pass, so a green
    run on a machine with no janitor daemon.log still proves the replay works."""
    pattern = read_worst_pass_pattern(_SYNTHETIC_WORST_PASS_LOG)
    _replay_and_assert(monkeypatch, pattern, scale=0.01, source="synthetic-fixture-log")


def test_replay_real_host_log_worst_pattern_keeps_tick_within_cadence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reads the worst measured pattern from the real host daemon.log (or
    JANITOR_REPLAY_LOG) at RUN TIME and replays it — the pattern is a parameter of
    whatever log window is available today, never a hard-coded duration. Skips (never
    fails) when no log is readable or it carries no parseable foreground bodies."""
    log_path_str = os.environ.get("JANITOR_REPLAY_LOG")
    log_path = Path(log_path_str).expanduser() if log_path_str else _DEFAULT_HOST_LOG
    if not log_path.is_file():
        pytest.skip(f"no readable daemon.log at {log_path} (set JANITOR_REPLAY_LOG to point elsewhere)")
    log_text = log_path.read_text(errors="replace")
    try:
        pattern = read_worst_pass_pattern(log_text)
    except ValueError as exc:
        pytest.skip(f"{log_path} carried no parseable foreground task bodies: {exc}")
    scale = float(os.environ.get("JANITOR_REPLAY_SCALE", "0.01"))
    _replay_and_assert(monkeypatch, pattern, scale=scale, source=str(log_path))
