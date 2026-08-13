"""The daemon's cold-cache-clear beat — the only actor that can shrink a session BEFORE a turn.

A cron fire's input cost is billed when the turn STARTS, and the dispatcher stub runs inside that
turn, so no in-session check can act in time. This beat is the answer to the owner's
*"if at any chron beat by any chance the cache is expired, doing the compact before running the
chron turn"*.

THE TEST THIS FILE EXISTS FOR is `test_it_reads_the_real_project_root_field`: the first draft read
`getattr(inst, "root", "")`, and `Instance` has no `root` — so every instance resolved to "" and
the whole beat would have shipped as a permanent no-op that logs nothing and looks exactly like
"nothing needed clearing". Nothing else in the suite would have noticed. The rest of the file
pins the safety gates, because the action being gated (`/clear`) is unrecoverable.
"""

from __future__ import annotations

import importlib.util as _u
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_DAEMON = _ROOT / "scripts" / "daemon.py"
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import fleet_scan  # noqa: E402


def _daemon():
    spec = _u.spec_from_file_location("janitor_daemon_cold_cache_under_test", str(_DAEMON))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _instance(root: str, *, pid: int = 4242, active: bool = False) -> fleet_scan.Instance:
    """A REAL `fleet_scan.Instance`, never a stub.

    Load-bearing: a hand-rolled stub with the fields the code happens to read would have
    accepted the `root` typo the module docstring describes. Constructing the real dataclass is
    what makes a renamed field a failure here instead of a silent no-op in production.
    """
    return fleet_scan.Instance(
        pid=pid,
        command="claude",
        tty="ttys001",
        project_root=root,
        terminal={"kind": "tmux", "pane": "%1"},
        diagnosis="ok",
        recovery=None,
        dispatch_age_s=10,
        active=active,
        transcript_age_s=9000,
    )


@pytest.fixture
def wired(monkeypatch):
    """The beat with its opt-in ON, its fleet injected, and only the WATCHER spawn captured.

    The spy must FILTER, not swallow. `monkeypatch.setattr(d.subprocess, "Popen", ...)` patches
    the stdlib module object, so it intercepts every Popen in the process — including the
    `subprocess.run(["git", "rev-parse", ...])` that `state.project_root()` performs when the
    beat logs. A blanket fake breaks `subprocess.run` (which needs a context manager) and the
    failure surfaces far from its cause. `_workload_spawn_spy` in test_daemon.py hit exactly
    this; the honest fix is the same one — key on argv, delegate everything else to the real
    Popen.
    """
    d = _daemon()
    spawns: list[list[str]] = []
    real_popen = d.subprocess.Popen

    def cap(*a, **k):
        argv = list(a[0]) if a else []
        if any(str(x).endswith("external_handoff_clear.py") for x in argv):
            spawns.append(argv)

            class _Stub:  # never actually run the watcher — it would type /clear into a pane
                pid = 99999

            return _Stub()
        return real_popen(*a, **k)

    monkeypatch.setattr(d.subprocess, "Popen", cap)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_ENABLED", "1")
    return d, spawns


def _project(tmp_path: Path, name: str = "proj") -> str:
    p = tmp_path / name
    (p / ".janitor" / "state").mkdir(parents=True, exist_ok=True)
    return str(p)


def test_it_reads_the_real_project_root_field(wired, monkeypatch, tmp_path: Path) -> None:
    """THE regression. `Instance.project_root` is the field; a `getattr(inst, "root", "")` read
    resolves to "" for every instance and turns the whole beat into a silent no-op.

    Asserting the spawn CARRIES the root is what makes that unmissable: a no-op produces no
    spawn, and a spawn with the wrong root would clear the wrong session.
    """
    d, spawns = wired
    root = _project(tmp_path)
    monkeypatch.setattr(d.fleet_scan, "gather_fleet", lambda **_k: [_instance(root)])

    d.task_cold_cache_clear()

    assert len(spawns) == 1, "a cold, idle session must be evaluated — no spawn means a no-op"
    assert root in spawns[0], f"the spawn must name the session's own root: {spawns[0]}"
    assert "--project-root" in spawns[0]
    assert spawns[0][1].endswith("external_handoff_clear.py"), (
        "it must DELEGATE to the watcher — reimplementing an unrecoverable /clear here would be "
        "a second implementation of the gate, the handoff and the injection chain"
    )


def test_it_is_inert_until_opted_in(wired, monkeypatch, tmp_path: Path) -> None:
    """`/clear` is unrecoverable, so the capability ships OFF — same opt-in as the hook half."""
    d, spawns = wired
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_ENABLED", raising=False)
    monkeypatch.setattr(
        d.fleet_scan, "gather_fleet", lambda **_k: [_instance(_project(tmp_path))]
    )

    d.task_cold_cache_clear()

    assert spawns == []


def test_it_never_clears_a_session_that_is_working(wired, monkeypatch, tmp_path: Path) -> None:
    """`active` means the transcript is ADVANCING — a live turn. Clearing that destroys work in
    flight, and unlike a keystroke injection it cannot be deferred-and-retried into safety, so it
    is a hard skip rather than a wait."""
    d, spawns = wired
    monkeypatch.setattr(
        d.fleet_scan,
        "gather_fleet",
        lambda **_k: [_instance(_project(tmp_path), active=True)],
    )

    d.task_cold_cache_clear()

    assert spawns == [], "a session with an advancing transcript must never be cleared"


def test_it_skips_a_session_with_no_janitor_state(wired, monkeypatch, tmp_path: Path) -> None:
    """No `.janitor/state` means the janitor was never armed there — not our session to clear."""
    d, spawns = wired
    bare = tmp_path / "unarmed"
    bare.mkdir()
    monkeypatch.setattr(d.fleet_scan, "gather_fleet", lambda **_k: [_instance(str(bare))])

    d.task_cold_cache_clear()

    assert spawns == []


def test_it_honours_the_clear_cooldown(wired, monkeypatch, tmp_path: Path) -> None:
    """A session cleared moments ago must not be cleared again on the next beat — without this
    the 5-minute cadence would re-clear the same session forever."""
    import cold_cache_compact  # noqa: PLC0415

    d, spawns = wired
    root = _project(tmp_path)
    monkeypatch.setattr(d.fleet_scan, "gather_fleet", lambda **_k: [_instance(root)])
    monkeypatch.setattr(cold_cache_compact, "clear_in_cooldown", lambda *_a, **_k: True)
    monkeypatch.setitem(sys.modules, "cold_cache_compact", cold_cache_compact)

    d.task_cold_cache_clear()

    assert spawns == []


def test_it_evaluates_only_one_session_per_beat(wired, monkeypatch, tmp_path: Path) -> None:
    """Firing N clears from one beat means N children each holding a fleet-lane ticket, and the
    last ticket is minutes out — they would pile up faster than they drain. One per beat lets a
    20-session fleet settle over ~20 beats with at most one child alive at a time."""
    d, spawns = wired
    fleet = [
        _instance(_project(tmp_path, f"p{i}"), pid=5000 + i)
        for i in range(5)
    ]
    monkeypatch.setattr(d.fleet_scan, "gather_fleet", lambda **_k: fleet)

    d.task_cold_cache_clear()

    assert len(spawns) == 1, "at most one clear may be started per beat"


def test_a_failed_fleet_scan_does_not_kill_the_beat(wired, monkeypatch) -> None:
    """A scan fault must log and return — a raising task would take down the daemon beat that
    also owns OAuth rotation and the memory guard."""
    d, spawns = wired

    def _boom(**_k):
        raise RuntimeError("ps exploded")

    monkeypatch.setattr(d.fleet_scan, "gather_fleet", _boom)

    d.task_cold_cache_clear()  # must not raise

    assert spawns == []


def test_it_is_registered_on_the_daemon_task_table() -> None:
    """A task nobody schedules is a task that does not exist — the same shipped-dead shape as
    the `root` typo, one layer up."""
    d = _daemon()
    src = _DAEMON.read_text(encoding="utf-8")
    assert 'Task("cold-cache-clear"' in src, "the beat must be in the daemon's task table"
    assert d._INTERVAL_COLD_CACHE_CLEAR > 0
