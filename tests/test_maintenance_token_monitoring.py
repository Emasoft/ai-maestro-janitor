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
