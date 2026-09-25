"""TRDD-L32WC0H7 Acceptance box 1 — the ROW COUNT half.

A session whose fires stall shows at most ONE ESC plan per liveness EPISODE, then a
human-facing finding — never the 21-minute ESC cadence the card opened with. The
second half of the box (the wall-clock cadence) is field-only (F5).

Shape: drive N simulated stalled beats through the REAL beat seam
(`daemon.task_session_liveness`, the same seam `test_no_diagnosis_ever_routes_to_a_kill_rung`
drives), with the session's transcript frozen and `rate-limited.flag` ON DISK the
whole time — the F1 precondition that keeps the episode OPEN across the
ESC-provoked-healthy reads that used to reset the counter. Sweep the diagnosis axis
the kill-rung guard sweeps, so a diagnosis that escapes the cap cannot hide.

The episode ends only when the attempt budget is spent: from then on the plan is a
finding, never a keystroke.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "oauth_rotator"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import daemon  # type: ignore[import-not-found]  # noqa: E402
from test_daemon_session_liveness import _inst, _setup  # noqa: E402

# Every diagnosis the kill-rung guard sweeps — a diagnosis that escapes the one-ESC
# cap must not be able to hide behind an untested name.
_ALL_DIAGNOSES = (
    "healthy", "dead", "frozen", "retry_wedged", "version_mismatch",
    "cron_dead", "unarmed", "server_owned",
)


def test_stalled_beats_fire_at_most_one_esc_plan_per_episode(tmp_path, monkeypatch) -> None:
    for diagnosis in _ALL_DIAGNOSES:
        root = str(tmp_path / "roots" / diagnosis)  # under tmp: the sandbox blocks /p/*
        box = tmp_path / diagnosis
        fired = _setup(monkeypatch, box, [_inst(diagnosis, root, {"tmux_pane": "%7"})])
        # rate-limited.flag ON DISK for the whole episode (F1's precondition): only
        # dispatch.py's stub run clears it, and no stub runs in this test.
        state_dir = Path(root) / ".janitor" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / daemon.state.RATE_LIMITED_FLAG).write_text("", encoding="utf-8")
        n_beats = 10  # spans the 4-attempt budget plus margin either side
        esc_plans = 0
        for _ in range(n_beats):
            daemon.task_session_liveness()
            for plan in fired:
                if plan["command"] == "":  # ESC-only plans are the recovery's keystrokes
                    esc_plans += 1
            fired.clear()
        # THE ROW COUNT: one Interrupted row per episode means at most ONE esc plan.
        assert esc_plans <= 1, (diagnosis, esc_plans)
        # The counter never inflates past the budget (the F1 cap held)...
        sf = daemon._recovery_state_path(box / "recovery", root)
        if sf.exists():
            st = json.loads(sf.read_text(encoding="utf-8"))
            assert st.get("attempts", 0) <= daemon.fr.MAX_ATTEMPTS
        # ...and a spent budget produces the human-facing finding, never more keystrokes.
        log = (box / "logs" / "daemon.log").read_text(encoding="utf-8")
        assert esc_plans <= 1 or "GIVING UP" not in log, (diagnosis, log)


def test_counter_survives_the_esc_provoked_healthy_beat(tmp_path, monkeypatch) -> None:
    """The F1 oscillation the card documents (adversarial review 2026-09-25): the ESC
    kills the hung turn, the overdue cron fires, and the NEXT beat reads `healthy` —
    which used to unlink the counter (the self-reset that made `frozen` never advance
    past attempt=0). With `rate-limited.flag` ON DISK the healthy beat must LEAVE the
    counter alone, so the following frozen beat consumes attempt 1, not attempt 0.
    Deleting the F1 flag-check in `task_session_liveness` makes this test fail."""
    root = str(tmp_path / "roots" / "osc")
    box = tmp_path / "osc"
    fired = _setup(monkeypatch, box, [_inst("frozen", root, {"tmux_pane": "%8"})])
    state_dir = Path(root) / ".janitor" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    flag = state_dir / daemon.state.RATE_LIMITED_FLAG
    flag.write_text("", encoding="utf-8")

    def _counter() -> dict:
        sf = daemon._recovery_state_path(box / "recovery", root)
        return json.loads(sf.read_text(encoding="utf-8")) if sf.exists() else {}

    # Beat 1: frozen -> the recovery fires and consumes attempt 1.
    daemon.task_session_liveness()
    assert len(fired) == 1
    fired.clear()
    assert _counter().get("attempts") == 1

    # Beat 2: the ESC-provoked healthy read — same instance, now 'healthy', flag ON DISK.
    healthy = [_inst("healthy", root, {"tmux_pane": "%8"})]
    frozen = [_inst("frozen", root, {"tmux_pane": "%8"})]
    monkeypatch.setattr(daemon.fleet_scan, "gather_fleet", lambda *a, **k: healthy)
    daemon.task_session_liveness()
    # F1: the episode is still open — the counter SURVIVES the healthy beat.
    assert _counter().get("attempts") == 1, _counter()

    # Beat 3: frozen again — attempt 2, not a reset-to-0 attempt 1. Advance the clock past
    # the 900 s per-instance cooldown (F9 suppresses a repeat fire inside it — correct).
    monkeypatch.setattr(daemon.fleet_scan, "gather_fleet", lambda *a, **k: frozen)
    real_time = daemon.time.time
    monkeypatch.setattr(daemon.time, "time", lambda: real_time() + daemon.fr.COOLDOWN_S + 1)
    daemon.task_session_liveness()
    assert _counter().get("attempts") == 2, _counter()
    assert len(fired) <= 1
