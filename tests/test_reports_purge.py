"""Tests for the reports-purge detector (S8, TRDD-LCO8229M).

Same harness as the screenshot-purge tests: run the detector as a subprocess (the real
dispatch invocation surface) with CLAUDE_PROJECT_DIR at a tmp tree; synthetic mtimes via
os.utime keep age boundaries deterministic and the suite fast.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DETECTOR = _PROJECT_ROOT / "scripts" / "detectors" / "reports-purge.py"

assert _DETECTOR.is_file(), f"detector not found at {_DETECTOR}"

_DAY = 86400


def _mk(path: Path, *, age_days: float = 0.0, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if age_days:
        ts = time.time() - age_days * _DAY
        os.utime(path, (ts, ts))
    return path


def _run(project: Path, **env_over: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(project)
    env.update(env_over)
    return subprocess.run(
        [sys.executable, str(_DETECTOR)], env=env, capture_output=True, text=True, timeout=60
    )


def test_age_boundary_purges_only_old_files(tmp_path: Path) -> None:
    """Files past the 30d default go; younger files and .gitkeep stay; empty dirs are
    cleaned; the summary line reports the count."""
    old = _mk(tmp_path / "reports" / "audit" / "old.md", age_days=31)
    young = _mk(tmp_path / "reports" / "audit" / "young.md", age_days=29)
    keep = _mk(tmp_path / "reports" / "lone" / ".gitkeep", age_days=90)
    gone_dir = _mk(tmp_path / "reports" / "emptyme" / "stale.md", age_days=40).parent
    res = _run(tmp_path)
    assert res.returncode == 0, res.stderr
    assert not old.exists() and young.exists() and keep.exists()
    assert not gone_dir.exists()  # emptied → removed
    assert (tmp_path / "reports").is_dir()  # the root itself always survives
    assert "removed 2 report file(s)" in res.stdout


def test_screenshots_subtree_is_never_touched(tmp_path: Path) -> None:
    """reports/screenshots/ belongs to screenshot-purge — even ancient files survive."""
    shot = _mk(tmp_path / "reports" / "screenshots" / "ancient.png", age_days=365)
    res = _run(tmp_path)
    assert res.returncode == 0, res.stderr
    assert shot.exists()


def test_opt_out_env_leaves_everything(tmp_path: Path) -> None:
    """CLAUDE_PLUGIN_OPTION_REPORTS_PURGE_ENABLED=false → full no-op."""
    old = _mk(tmp_path / "reports" / "old.md", age_days=90)
    res = _run(tmp_path, CLAUDE_PLUGIN_OPTION_REPORTS_PURGE_ENABLED="false")
    assert res.returncode == 0 and res.stdout == ""
    assert old.exists()


def test_max_age_zero_disables_reports_half_only(tmp_path: Path) -> None:
    """REPORTS_MAX_AGE_DAYS=0 keeps every report but the seen-file cap still runs."""
    old = _mk(tmp_path / "reports" / "old.md", age_days=90)
    seen = _mk(
        tmp_path / ".janitor" / "state" / "dirty-tree-seen.txt",
        text="\n".join(f"k{i}" for i in range(600)) + "\n",
    )
    res = _run(
        tmp_path,
        CLAUDE_PLUGIN_OPTION_REPORTS_MAX_AGE_DAYS="0",
        CLAUDE_PLUGIN_OPTION_SEEN_FILE_MAX_LINES="500",
    )
    assert res.returncode == 0, res.stderr
    assert old.exists()
    lines = seen.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 500
    assert lines[-1] == "k599" and lines[0] == "k100"  # NEWEST tail preserved


def test_seen_file_cap_preserves_newest_and_dedupe_still_works(tmp_path: Path) -> None:
    """The trim keeps the tail (emit_once appends), so recent keys still dedupe."""
    seen = _mk(
        tmp_path / ".janitor" / "state" / "provenance-seen.txt",
        text="\n".join(f"hash-{i}" for i in range(510)) + "\n",
    )
    small = _mk(tmp_path / ".janitor" / "state" / "small-seen.txt", text="a\nb\n")
    res = _run(tmp_path, CLAUDE_PLUGIN_OPTION_SEEN_FILE_MAX_LINES="500")
    assert res.returncode == 0, res.stderr
    lines = seen.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 500 and lines[-1] == "hash-509"
    assert small.read_text(encoding="utf-8") == "a\nb\n"  # under cap → untouched
    assert "capped 1 seen-file(s)" in res.stdout


def test_no_reports_dir_is_silent(tmp_path: Path) -> None:
    """Common case on fresh projects: nothing to do, zero output."""
    res = _run(tmp_path)
    assert res.returncode == 0 and res.stdout == ""
