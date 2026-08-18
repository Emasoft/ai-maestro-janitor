"""safe_delete.py exit-code contract — per-target semantics (hub P1, 2026-08-18).

The rule (rules/use-safe-delete.md) documents per-target semantics: every
target either moves into .trashcan/ or is reported, and the exit code is
non-zero when ANY target failed — even if others moved. The old gate
(`failed > 0 and moved == 0`) returned 0 on a 1-of-3 partial, hiding the
partial from every caller that trusts exit codes. These are REAL subprocess
runs against a temp project dir (CLAUDE_PROJECT_DIR pins the root), no mocks.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "safe_delete.py"


def _run(project: Path, *paths: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(project)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *paths],
        capture_output=True, text=True, check=False, cwd=project, env=env,
    )


def test_all_targets_moved_exits_zero(tmp_path: Path) -> None:
    """A fully successful batch exits 0 and every target lands in .trashcan/."""
    a = tmp_path / "a.txt"
    b = tmp_path / "sub" / "b.txt"
    b.parent.mkdir()
    a.write_text("a")
    b.write_text("b")
    proc = _run(tmp_path, str(a), str(b))
    assert proc.returncode == 0, proc.stderr
    assert not a.exists() and not b.exists()
    batches = [p for p in (tmp_path / ".trashcan").iterdir() if p.is_dir()]
    assert len(batches) == 1
    assert (batches[0] / "a.txt").is_file()
    assert (batches[0] / "sub" / "b.txt").is_file()


def test_partial_failure_moves_valid_targets_but_exits_nonzero(tmp_path: Path) -> None:
    """1-of-2 missing: the valid target still moves (recoverable by design) but the exit is non-zero."""
    ok = tmp_path / "ok.txt"
    ok.write_text("x")
    proc = _run(tmp_path, str(ok), str(tmp_path / "missing.txt"))
    assert proc.returncode == 1, f"partial failure must be visible in the exit code\n{proc.stderr}"
    assert not ok.exists(), "the valid target must still be trashed (per-target semantics)"
    assert "does not exist" in proc.stderr


def test_all_targets_failed_exits_nonzero_and_moves_nothing(tmp_path: Path) -> None:
    """An all-failed batch exits non-zero and leaves no timestamp dir behind."""
    proc = _run(tmp_path, str(tmp_path / "nope.txt"))
    assert proc.returncode == 1
    trash = tmp_path / ".trashcan"
    assert not trash.exists() or not any(p.is_dir() for p in trash.iterdir())
