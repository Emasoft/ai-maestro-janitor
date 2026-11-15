"""env-secret-on-disk's wiring (janitor issue #354).

A detector that is not on the roster NEVER RUNS (that omission kept token-usage-anomaly dark for weeks,
TRDD-E9LMBNPE), so leaving this one off is a decision, and the first test pins it. The detector's behaviour is
tested in test_env_secret_on_disk_detector.py; this pins only the wiring: NOT scheduled yet (on demand only),
executable, and its issue code known to the catalog.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def test_it_is_not_scheduled_until_its_walk_is_bounded() -> None:
    """On demand only, by decision (TRDD-G14LKPEC). Measured 2026-11-15 on a project whose agent folders hold 1.2
    million files: one pass took 49 s and 55 s, because sweep() lists and stats every file BEFORE its time budget
    starts, and it reads the oldest change first, so a fresh leak waits behind the whole backlog. On the hourly
    roster that is about a minute of every heartbeat fire that runs it, on a project whose agent folders are that large, for a finding that
    arrives days late. Add the roster row back, and change this test, only once both are fixed."""
    sys.path.insert(0, str(_ROOT / "scripts"))
    import dispatch  # noqa: PLC0415

    assert not [row for row in dispatch._DETECTORS if row[0] == "env-secret-on-disk"]


def test_the_detector_file_is_executable() -> None:
    """It is run directly (on demand: uv run <plugin>/scripts/detectors/env-secret-on-disk.py); a missing executable
    bit would also be a silent no-op once it is scheduled."""
    detector = _ROOT / "scripts" / "detectors" / "env-secret-on-disk.py"
    assert detector.is_file() and os.access(detector, os.X_OK)


def test_its_issue_code_is_known_and_owned_by_the_detector() -> None:
    """CRED-002 exists in the catalog, is emitted by this detector, and is a PROJECT-domain leaked-credential finding."""
    sys.path.insert(0, str(_ROOT / "scripts" / "lib"))
    import issue_catalog  # noqa: PLC0415

    issue = issue_catalog.ISSUE_CATALOG["CRED-002"]
    assert issue.scanner == "env-secret-on-disk" and issue.kind == "leaked-credential"
    assert "env-secret-on-disk" in issue_catalog.scanners()
