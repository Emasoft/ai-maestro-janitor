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
