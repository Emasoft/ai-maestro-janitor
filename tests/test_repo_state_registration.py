"""repo-state's dispatch registration (TRDD-DG2V7D5P).

A detector that is not on the roster NEVER RUNS — that exact omission kept
token-usage-anomaly dark for weeks (TRDD-E9LMBNPE). The detector file and its own
tests live elsewhere; this pins only the wiring: scheduled, exactly once, and
advisory (ahead/behind counts are "consider pushing", never urgent).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def test_repo_state_is_registered_once_and_is_advisory() -> None:
    sys.path.insert(0, str(_ROOT / "scripts"))
    import dispatch  # noqa: PLC0415

    names = [name for name, _interval, _env in dispatch._DETECTORS]
    assert names.count("repo-state") == 1, (
        f"repo-state must appear in the schedule table exactly once; found {names.count('repo-state')}"
    )
    assert "repo-state" in dispatch._ADVISORY_DETECTORS, (
        "repo-state is informational (ahead/behind counts) — it must be on the advisory list"
    )


def test_repo_state_detector_file_is_executable() -> None:
    """The roster names a FILE; a typo there is a silent no-op."""
    det = _ROOT / "scripts" / "detectors" / "repo-state.py"
    assert det.is_file(), f"roster names a detector that does not exist: {det}"
    assert os.access(det, os.X_OK), "detector must be executable (the roster runs it directly)"
