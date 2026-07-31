"""INVERTED — token monitoring no longer has to SURVIVE anything (was TRDD-8Q0OYVWM).

User directive 2026-07-10: "make sure the janitor heartbeat even in maintenance mode will keep
the token monitoring on". Maintenance idled every chore, so dispatch carried a SUBSET
(`_MAINTENANCE_DETECTORS`) that ran inside the maintenance branch while the rest stayed idle.
The directive was right and the subset was the wrong shape for it: an allowlist that decides
which guards survive a quiet mode is a list someone must remember to extend, and everything not
on it fails silently by design.

Maintenance mode is gone (owner directive 2026-07-31), which answers the 2026-07-10 directive
completely and permanently: there is no mode in which a detector does not run. These tests are
kept, not deleted, because the subset is exactly what a future "cheap mode" would re-introduce —
and the two detectors it named are the ones that watch token burn on an unattended session, the
last thing that should ever be conditionally skipped.

Real imports, no mocks beyond recording seams.
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


def test_there_is_no_detector_subset_and_no_second_runner() -> None:
    """Both halves are asserted: a surviving LIST invites a new runner, and a surviving RUNNER
    invites a new list. Either one alone rebuilds the "some detectors are optional" shape."""
    dispatch = _import_dispatch()
    assert not hasattr(dispatch, "_MAINTENANCE_DETECTORS")
    assert not hasattr(dispatch, "_run_maintenance_detectors")


def test_the_token_monitors_are_still_in_the_real_roster() -> None:
    """The two detectors the subset existed to protect must still be scheduled — the subset went
    away because they are unconditional now, NOT because they stopped mattering. Asserted against
    the REAL `_DETECTORS` roster, which is the only thing that runs them."""
    dispatch = _import_dispatch()
    roster = {name for name, _, _ in dispatch._DETECTORS}
    for name in ("token-usage-anomaly", "window-burn-rate"):
        assert name in roster, f"{name} must remain on the heartbeat roster"


def test_main_has_no_mode_branch_that_skips_the_detector_loop() -> None:
    """Source-order guard (same technique as the heartbeat-cost phase test): main() must reach its
    detector loop with no early `return 0` gated on a MODE in between.

    Only `mode == "stop"` may end a fire before the detectors, and it does so by DELETING the cron
    (a self-disarm), which is observable from outside the process. Every other early return in
    main() is a RESUME path — a fire that hands the turn to the model instead of doing chores, and
    which the very next fire follows up on. What may never come back is a branch that keeps firing
    on schedule and silently skips the work."""
    src = (_PROJECT_ROOT / "scripts" / "dispatch.py").read_text(encoding="utf-8")
    body = src[src.index("def main(") :]
    assert 'if mode == "maintenance":' not in body
    # The only mode branch left is the self-disarm, and it must precede everything else.
    stop = body.index('if mode == "stop":')
    detectors = body.index("for name, default_interval, env_var in _DETECTORS:")
    assert stop < detectors
    assert body.count("mode ==") == 1, "exactly one mode branch may exist"
