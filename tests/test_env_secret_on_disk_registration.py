"""env-secret-on-disk's wiring (janitor issue #354).

A detector that is not on the roster NEVER RUNS (that omission kept token-usage-anomaly dark for weeks,
TRDD-E9LMBNPE), so the roster row is pinned. The detector's behaviour is tested in test_env_secret_on_disk_detector.py;
this pins only the wiring: scheduled hourly and deferred under host pressure, executable, and its issue code known
to the catalog.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def test_it_is_on_the_hourly_roster_once() -> None:
    """Scheduled hourly (TRDD-ZANQ1QW0). It was held off the roster by TRDD-G14LKPEC because of a 2026-11-15
    measurement on a project whose agent folders hold 1.2 million files: one pass took 49 s and 55 s, since sweep()
    listed and stat-ed every file before its time budget started and read the oldest change first, so a fresh leak
    waited behind the whole backlog. Four changes fixed that: increment 3 (a covered modification-time range, newest
    first, and a bounded listing), increment 4 (one pass at a time per project, flock), increment 5 (a hard read
    bound per sweep, 75 s main and 25 s trash, checked between chunks) and TRDD-ZFD3KBM3 (a finding is withdrawn only
    for a secret the pass held). Exactly one row, at 3600 s, with its own interval variable."""
    sys.path.insert(0, str(_ROOT / "scripts"))
    import dispatch  # noqa: PLC0415

    rows = [row for row in dispatch._DETECTORS if row[0] == "env-secret-on-disk"]
    assert rows == [("env-secret-on-disk", 3600, "CLAUDE_PLUGIN_OPTION_ENV_SECRET_ON_DISK_INTERVAL")]


def test_it_is_deferred_under_host_pressure() -> None:
    """It lists every file of the agent-written folders (about a million on a large host) and reads up to 256 MiB, so
    it belongs in the pressure-heavy set: a busy host defers it, and a deferred detector stays due (not stamped)."""
    sys.path.insert(0, str(_ROOT / "scripts"))
    import dispatch  # noqa: PLC0415

    assert "env-secret-on-disk" in dispatch._PRESSURE_HEAVY_DETECTORS


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
