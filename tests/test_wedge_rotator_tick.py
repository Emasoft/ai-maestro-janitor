"""Wedge-triggered immediate rotator tick (TRDD-GXXKAGY6).

A confirmed retry wedge on a pane is a 429-shaped wall the ROTATOR is the remedy for, yet
before this change the rotation waited for the next 60 s `oauth-rotator-tick` beat — an
arbitrary wait on top of an already-confirmed wall (TRDD-4XND73XD D7: a trigger only
SCHEDULES a tick; the tick keeps every guard).

Two units under test, mirroring test_release_triggered_self_update.py's structure:
  * `daemon._consume_rotator_tick_request` — the daemon's clear-before-run consume, driven
    with a REAL `daemon.Task` spy (no subprocess / network); plus the raise site: the
    session-liveness beat's `retry_wedged` branch requests a tick.
  * `rotator.wedge_tick_requested` / cmd_auto — the wedge context crosses the subprocess
    boundary as `JANITOR_ROTATOR_WEDGE_TICK=1` (the JANITOR_ROTATOR_HEADLESS env
    precedent) and counts the live 429 as ALREADY debounced (the heuristic the owner
    settled as "it depends on the context. use heuristic."): a confirmed wedge has already
    satisfied the repeated-observation bar LIVE_429_DEBOUNCE exists to enforce, so a
    wedge-scheduled tick rotates on the FIRST 429 probe, while an ordinary-beat tick
    still defers it (byte-identical to the pre-GXXKAGY6 behaviour).
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

_LIB = Path(__file__).resolve().parent.parent / "scripts" / "lib"
sys.path.insert(0, str(_LIB))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "oauth_rotator"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
daemon = importlib.import_module("daemon")
gs = importlib.import_module("global_state")
rotator = importlib.import_module("rotator")


@pytest.fixture(autouse=True)
def _isolate_janitor_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect every janitor global-state / DATA / HOME path to a per-test tmp tree so no
    test reads or writes the real ~/.claude/janitor-global-state/ or the plugin DATA dir."""
    home = tmp_path / "_home"
    data = home / ".claude" / "plugins" / "data" / "ai-maestro-janitor-ai-maestro-plugins"
    gsd = tmp_path / "_global-state"
    for d in (home, data, gsd):
        d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(gsd))
    monkeypatch.setenv("JANITOR_DATA_DIR", str(data))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(data))
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.delenv("JANITOR_ROTATOR_WEDGE_TICK", raising=False)
    for fn in (daemon.state.project_root, daemon.state.janitor_root,
               daemon.state.state_dir, daemon.state.log_dir):
        fn.cache_clear()


# ---------- the request-flag trio (global_state) --------------------------

def test_request_present_clear_roundtrip() -> None:
    """request() sets the flag, present() sees it, clear() removes it."""
    assert gs.rotator_tick_requested_present() is False
    gs.request_rotator_tick("retry-wedged-esc")
    assert gs.rotator_tick_requested_present() is True
    gs.clear_rotator_tick_request()
    assert gs.rotator_tick_requested_present() is False

import time  # noqa: E402  # fastedit cannot edit the top import block


def _wait_for(pred, timeout: float = 5.0) -> bool:  # type: ignore[no-untyped-def]
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False

def _fresh_ticker(task):  # type: ignore[no-untyped-def]
    """A tick thread whose task just ran, so only a wedge request (not the beat) can run it."""
    daemon.state.atomic_write(task.last_run_path, str(int(time.time())))
    return daemon._RotatorTickThread(task)


# ---------- the daemon consume-helper + the raise site --------------------

def test_consume_runs_the_tick_once_and_clears_flag() -> None:
    """Flag set => the tick THREAD runs the Task exactly once, flag cleared, True."""
    calls: list[str] = []
    task = daemon.Task("oauth-rotator-tick", 3600, lambda: calls.append("ran"), own_thread=True)
    ticker = _fresh_ticker(task)
    ticker.start()
    try:
        gs.request_rotator_tick("retry-wedged-esc")

        consumed = daemon._consume_rotator_tick_request(ticker)

        assert consumed is True
        assert _wait_for(lambda: bool(calls)), "the wedge request must run the rotator tick"
        time.sleep(1.5)
        assert calls == ["ran"], "the wedge request must run the rotator tick exactly once"
        assert gs.rotator_tick_requested_present() is False, "the flag must be cleared on consume"
    finally:
        ticker.shutdown(5)


def test_consume_is_a_noop_when_no_request() -> None:
    """No flag => False and nothing runs (the 60 s beat keeps owning the tick)."""
    calls: list[str] = []
    task = daemon.Task("oauth-rotator-tick", 3600, lambda: calls.append("ran"), own_thread=True)
    ticker = _fresh_ticker(task)
    ticker.start()
    try:
        assert daemon._consume_rotator_tick_request(ticker) is False
        time.sleep(1.5)
        assert calls == []
    finally:
        ticker.shutdown(5)


def test_consume_runs_only_the_tick_not_sibling_tasks() -> None:
    """The thread runs only its own task — never a sibling chore of the same roster."""
    ran: list[str] = []
    tasks = [
        daemon.Task("github-config-audit", 1200, lambda: ran.append("github-config-audit")),
        daemon.Task("oauth-rotator-tick", 3600, lambda: ran.append("oauth-rotator-tick"), own_thread=True),
        daemon.Task("version-update", 21600, lambda: ran.append("version-update")),
    ]
    ticker = _fresh_ticker(tasks[1])
    ticker.start()
    try:
        gs.request_rotator_tick("retry-wedged-esc")
        daemon._consume_rotator_tick_request(ticker)
        assert _wait_for(lambda: bool(ran))
        time.sleep(1.5)
        assert ran == ["oauth-rotator-tick"], "only the rotator tick may run on consume"
    finally:
        ticker.shutdown(5)


def test_the_wedge_scheduled_tick_carries_the_env_and_beat_does_not() -> None:
    """The wedge context must cross the subprocess boundary as JANITOR_ROTATOR_WEDGE_TICK=1
    exactly while the wedge-scheduled task body runs, and be gone for a beat-scheduled run —
    the env var is the rotator's ONLY channel for this (it runs as a subprocess)."""
    observed: list[str | None] = []

    def _spy() -> None:
        observed.append(os.environ.get("JANITOR_ROTATOR_WEDGE_TICK"))

    task = daemon.Task("oauth-rotator-tick", 3600, _spy, own_thread=True)
    ticker = _fresh_ticker(task)
    ticker.start()
    try:
        gs.request_rotator_tick("retry-wedged-esc")
        daemon._consume_rotator_tick_request(ticker)
        assert _wait_for(lambda: observed == ["1"]), "the wedge-scheduled run must set the env"
        assert _wait_for(lambda: "JANITOR_ROTATOR_WEDGE_TICK" not in os.environ), "the env must be popped afterwards"
    finally:
        ticker.shutdown(5)

    task.run()  # the ordinary 60 s beat's path — no consume, no wedge context
    assert observed == ["1", None], "a beat-scheduled run must NOT inherit the wedge context"


def test_a_confirmed_retry_wedge_requests_a_tick(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """THE raise site: a session-liveness beat firing the `retry_wedged` ESC rung must also
    raise the immediate-tick request. This test fails without the GXXKAGY6 raise."""
    proj = tmp_path / "proj"
    proj.mkdir()
    inst = daemon.fleet_scan.Instance(
        pid=1, command="claude", tty="ttys1", project_root=str(proj),
        terminal={"tmux_pane": "%9"}, diagnosis="retry_wedged", recovery=None,
        dispatch_age_s=None, active=False, transcript_age_s=None,
    )
    monkeypatch.setenv("JANITOR_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(daemon.fleet_inject, "fire", lambda plan: True)
    monkeypatch.setattr(
        daemon.fleet_scan, "gather_fleet",
        lambda *, now, sweep_stale_rate_limit_s=None: [inst],
    )
    monkeypatch.setattr(daemon.user_intent, "hid_idle_seconds", lambda **kw: 600.0)
    monkeypatch.setattr(daemon.pane_actuate, "act", lambda *a, **k: daemon.pane_actuate.Outcome(
        status=daemon.pane_actuate.OutcomeStatus.DONE, steps_done=1, observed=(), touched=True))

    daemon.task_session_liveness()

    assert gs.rotator_tick_requested_present() is True, (
        "a confirmed retry wedge must schedule an immediate rotator tick"
    )


# ---------- the rotator heuristic (cmd_auto's live-429 gate) ----------------

def _blob(token: str) -> dict:
    return {"claudeAiOauth": {"accessToken": token, "refreshToken": "r"}}


def _setup_auto(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, live_status: int) -> list:
    """Wire cmd_auto's seams for a single live probe; returns the _switch_blob record list."""
    monkeypatch.setattr(rotator, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(rotator, "SLOTS", tmp_path / "slots")
    live = _blob("LIVE")
    rotator.save_state({"live_email": "live@x", "live_fp": rotator.fingerprint(live),
                        "slots": {"alt@x": {}}})
    monkeypatch.setattr(rotator, "read_live_blob_with_source", lambda: (live, "primary"))
    monkeypatch.setattr(rotator, "read_slot", lambda e: _blob("ALT") if e == "alt@x" else None)
    monkeypatch.setattr(rotator, "usage_request",
                        lambda b: (live_status, None) if b.get("claudeAiOauth", {}).get("accessToken") == "LIVE"
                        else (200, {"five_hour": {"utilization": 5.0}, "seven_day": {"utilization": 5.0}}))
    switches: list = []
    monkeypatch.setattr(rotator, "_switch_blob",
                        lambda email, blob, reason: switches.append((email, blob, reason)))
    return switches


def test_a_wedge_scheduled_tick_rotates_on_the_first_429(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """THE GXXKAGY6 heuristic: on a WEDGE-scheduled tick a live 429 counts as already
    debounced (the wedge's advance-across-polls evidence is the debounce), so the rotation
    happens on the FIRST probe instead of deferring to a second beat."""
    monkeypatch.setenv("JANITOR_ROTATOR_WEDGE_TICK", "1")
    switches = _setup_auto(monkeypatch, tmp_path, live_status=429)
    rotator.cmd_auto()
    assert [s[0] for s in switches] == ["alt@x"], (
        "a wedge-scheduled tick must treat the live 429 as debounced and rotate now"
    )


def test_an_ordinary_beat_tick_still_debounces_the_first_429(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CONTROL: without the wedge context the pre-GXXKAGY6 behaviour is byte-identical —
    the first live 429 defers (streak 1 < LIVE_429_DEBOUNCE), nothing rotates."""
    monkeypatch.delenv("JANITOR_ROTATOR_WEDGE_TICK", raising=False)
    switches = _setup_auto(monkeypatch, tmp_path, live_status=429)
    rotator.cmd_auto()
    assert switches == [], "an ordinary-beat tick must keep the LIVE_429_DEBOUNCE streak gate"


def test_wedge_debounced_rotation_still_respects_the_dwell_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """D7 (TRDD-4XND73XD): the wedge buys an EARLY tick, never a bypassed one — the
    MIN_DWELL_S anti-thrash guard still holds even on a wedge-scheduled run."""
    monkeypatch.setenv("JANITOR_ROTATOR_WEDGE_TICK", "1")
    switches = _setup_auto(monkeypatch, tmp_path, live_status=429)
    rotator.save_state({**rotator.load_state(), "last_switch_at": __import__("time").time() - 1})
    rotator.cmd_auto()
    assert switches == [], "a wedge-scheduled tick must still defer inside the dwell window"

def _daemon_tick_primary_read_permitted(monkeypatch: pytest.MonkeyPatch) -> bool:
    """Run the daemon's rotator-tick body with the rotator subprocess stubbed out, and report
    whether the env it would hand the subprocess lets the rotator do the `-w` primary read."""
    monkeypatch.setattr(daemon.oauth_supervisor, "opt_in_present", lambda: True)
    seen: list[bool] = []
    monkeypatch.setattr(
        daemon, "_run_workload",
        lambda *a, **k: seen.append(rotator._primary_secret_read_permitted()),
    )
    daemon.task_oauth_rotator_tick()
    return seen[0]


def test_daemon_tick_skips_primary_read_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """TRDD-ZKXQXHBI's daemon-context primary `-w` read is OFF unless explicitly opted in."""
    monkeypatch.delenv("JANITOR_ROTATOR_HEADLESS", raising=False)
    monkeypatch.delenv("JANITOR_ROTATOR_DAEMON_PRIMARY_READ", raising=False)
    assert _daemon_tick_primary_read_permitted(monkeypatch) is False


def test_daemon_tick_primary_read_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """JANITOR_ROTATOR_DAEMON_PRIMARY_READ=1 lets the daemon tick attempt the primary read."""
    monkeypatch.delenv("JANITOR_ROTATOR_HEADLESS", raising=False)
    monkeypatch.setenv("JANITOR_ROTATOR_DAEMON_PRIMARY_READ", "1")
    assert _daemon_tick_primary_read_permitted(monkeypatch) is True
