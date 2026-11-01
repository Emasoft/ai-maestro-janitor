"""Tests for the reports-purge detector (S8, TRDD-LCO8229M; TRDD-KSUIEPTQ, issue #350).

Run the detector as a subprocess (the real dispatch invocation surface) with CLAUDE_PROJECT_DIR
at a tmp tree. Since TRDD-KSUIEPTQ it only caps seen-files: reports/ is git-tracked project
content and reports_dev/ contents are never deleted.
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


def test_old_reports_and_reports_dev_files_are_never_deleted(tmp_path: Path) -> None:
    """Issue #350: reports/ is tracked work and reports_dev/ is never deleted — however old,
    and even under the retired REPORTS_MAX_AGE_DAYS option."""
    tracked = _mk(tmp_path / "reports" / "audit" / "old.md", age_days=365)
    raw = _mk(tmp_path / "reports_dev" / "audit" / "old.md", age_days=365)
    shot = _mk(tmp_path / "reports_dev" / "ui" / "screenshots" / "a.png", age_days=365)
    res = _run(tmp_path, CLAUDE_PLUGIN_OPTION_REPORTS_MAX_AGE_DAYS="1")
    assert res.returncode == 0, res.stderr
    assert tracked.exists() and raw.exists() and shot.exists()
    assert res.stdout == ""


def test_opt_out_env_leaves_everything(tmp_path: Path) -> None:
    """CLAUDE_PLUGIN_OPTION_REPORTS_PURGE_ENABLED=false → full no-op, seen-files included."""
    seen = _mk(
        tmp_path / ".janitor" / "state" / "dirty-tree-seen.txt",
        text="\n".join(f"k{i}" for i in range(600)) + "\n",
    )
    res = _run(tmp_path, CLAUDE_PLUGIN_OPTION_REPORTS_PURGE_ENABLED="false")
    assert res.returncode == 0 and res.stdout == ""
    assert len(seen.read_text(encoding="utf-8").splitlines()) == 600


def test_seen_cap_zero_disables_the_cap(tmp_path: Path) -> None:
    """SEEN_FILE_MAX_LINES=0 keeps every seen-file line."""
    seen = _mk(
        tmp_path / ".janitor" / "state" / "dirty-tree-seen.txt",
        text="\n".join(f"k{i}" for i in range(600)) + "\n",
    )
    res = _run(tmp_path, CLAUDE_PLUGIN_OPTION_SEEN_FILE_MAX_LINES="0")
    assert res.returncode == 0, res.stderr
    assert len(seen.read_text(encoding="utf-8").splitlines()) == 600


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
    assert len(lines) == 500 and lines[0] == "hash-10" and lines[-1] == "hash-509"
    assert small.read_text(encoding="utf-8") == "a\nb\n"  # under cap → untouched
    assert "capped 1 seen-file(s)" in res.stdout


def test_no_reports_dir_is_silent(tmp_path: Path) -> None:
    """Common case on fresh projects: nothing to do, zero output."""
    res = _run(tmp_path)
    assert res.returncode == 0 and res.stdout == ""
