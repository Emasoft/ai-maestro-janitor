"""Token monitoring survives maintenance mode (TRDD-8Q0OYVWM).

User directive 2026-07-10: "make sure the janitor heartbeat even in maintenance mode
will keep the token monitoring on". A maintenance session is the long-running
unattended one whose burn most needs watching, so dispatch runs ONLY the
token-monitoring detector subset inside the maintenance branch while every other
chore stays idle. Real imports, no mocks beyond recording seams.
"""

import importlib.util
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _PROJECT_ROOT / "scripts"


def _import_dispatch():
    for p in (str(_SCRIPTS), str(_SCRIPTS / "lib")):
        if p not in sys.path:
            sys.path.insert(0, p)
    spec = importlib.util.spec_from_file_location("dispatch_tmm", _SCRIPTS / "dispatch.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_subset_is_exactly_the_token_monitors() -> None:
    """The maintenance subset is the two token-burn detectors, nothing else."""
    dispatch = _import_dispatch()
    assert dispatch._MAINTENANCE_DETECTORS == {"token-usage-anomaly", "window-burn-rate"}


def test_subset_names_are_bound_to_the_roster() -> None:
    """Every subset name must be a real _DETECTORS roster entry — a renamed detector
    that leaves a stale subset name would silently stop token monitoring in
    maintenance (the four-readers-zero-writers lesson: bind names, don't repeat them)."""
    dispatch = _import_dispatch()
    roster = {name for name, _, _ in dispatch._DETECTORS}
    missing = dispatch._MAINTENANCE_DETECTORS - roster
    assert not missing, f"subset names not in the roster: {missing}"


def test_run_maintenance_detectors_runs_only_the_subset(monkeypatch) -> None:
    """_run_maintenance_detectors invokes _run_detector for the subset ONLY, with the
    roster's own cadence for each — never the full roster, never a foreign interval."""
    dispatch = _import_dispatch()
    ran: list[tuple[str, int]] = []
    monkeypatch.setattr(dispatch, "_run_detector", lambda name, interval: ran.append((name, interval)))
    dispatch._run_maintenance_detectors()
    names = {name for name, _ in ran}
    assert names == dispatch._MAINTENANCE_DETECTORS
    # Cadences come from the roster defaults (no env overrides in this test).
    roster = {name: default for name, default, _ in dispatch._DETECTORS}
    for name, interval in ran:
        assert interval == roster[name], f"{name} ran at {interval}, roster says {roster[name]}"


def test_self_budget_escalation_and_hysteresis_release(tmp_path, monkeypatch) -> None:
    """The self-budget maintenance ladder end-to-end (TRDD-ZCODD6YS): a crossed
    maintenance-tier budget writes the LOCAL MAINTENANCE_FLAG (never the global flag) so the
    NEXT fire's _resolve_heartbeat_mode returns 'maintenance'; a dead-band HOLD keeps it while
    cost hovers; and once cost decays below release_frac a subsequent (maintenance-mode) fire
    CLEARS the flag and the following fire resolves 'full' again — proving the throttle
    RELEASES, never pins the session cheap forever."""
    import json
    import time as _time

    project = tmp_path / "project"
    (project / ".janitor" / "state").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "global"))
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path / "control"))
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_SELF_BUDGET", "1000")
    for m in ("dispatch_tmm", "dispatch", "state", "global_state"):
        sys.modules.pop(m, None)

    dispatch = _import_dispatch()
    import global_state as gs
    import state

    gs.init_global_state()
    state.init_state()
    sd = state.state_dir()

    def seed(weighted: int) -> None:
        (sd / "token-meter.jsonl").write_text(
            json.dumps({"ts": int(_time.time()), "heartbeat": True, "output": weighted}) + "\n",
            encoding="utf-8",
        )

    # ENTER: 7d heartbeat cost over 0.9*budget → LOCAL maintenance flag; never the global one.
    seed(5000)
    assert dispatch._phase_self_budget() is True
    assert (sd / state.MAINTENANCE_FLAG).is_file(), "over the maintenance fraction → LOCAL flag written"
    assert gs.maintenance_mode_present() is False, "a per-project budget must never set the global flag"
    assert dispatch._resolve_heartbeat_mode() == "maintenance", "the NEXT fire resolves maintenance"

    # DEAD-BAND HOLD: cost drops to 0.5*budget (below cap/maint but ABOVE release 0.4) → the
    # Schmitt trigger holds maintenance so the flag does not flap.
    seed(500)
    assert dispatch._phase_self_budget() is True
    assert (sd / state.MAINTENANCE_FLAG).is_file(), "dead-band holds maintenance above the release band"

    # RELEASE: cost falls below release_frac*budget → flag cleared, the next fire is full again.
    seed(300)
    assert dispatch._phase_self_budget() is False
    assert not (sd / state.MAINTENANCE_FLAG).is_file(), "released once cost drained below the dead-band"
    assert dispatch._resolve_heartbeat_mode() == "full", "the session returns to full monitoring"


def test_main_runs_token_monitoring_inside_the_maintenance_branch() -> None:
    """Source-order guard (same technique as the heartbeat-cost phase test): the
    _run_maintenance_detectors() call must sit BETWEEN the maintenance branch entry
    and its return — inside the branch, so full mode never double-runs the subset
    (Phase 2 covers it there) and maintenance never skips it."""
    src = (_PROJECT_ROOT / "scripts" / "dispatch.py").read_text(encoding="utf-8")
    body = src[src.index("def main(") :]
    branch = body.index('if mode == "maintenance":')
    call = body.index("_run_maintenance_detectors()")
    ret = body.index("return 0", branch)
    assert branch < call < ret, (
        "_run_maintenance_detectors() must run inside the maintenance branch, "
        "before its early return"
    )
