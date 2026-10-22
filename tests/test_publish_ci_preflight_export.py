"""Tests for publish._export_head: the CI-parity preflight export must match a CI checkout.

WHY: a `git archive` export had no `.git` and honored export-ignore, which a real
checkout does not. Real git repos in tmp_path, no mocks.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import publish  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def test_export_head_matches_ci_checkout(tmp_path: Path) -> None:
    """Clone has tracked + export-ignored files, a real .git, same HEAD, no gitignored files."""
    src = tmp_path / "src"
    src.mkdir()
    _git(src, "init", "--quiet")
    _git(src, "config", "user.name", "Test")
    _git(src, "config", "user.email", "test@example.invalid")
    (src / "tracked.txt").write_text("t\n")
    (src / "secret.txt").write_text("s\n")
    (src / ".gitignore").write_text("ignored_dir/\n")
    (src / ".gitattributes").write_text("secret.txt export-ignore\n")
    _git(src, "add", "tracked.txt", "secret.txt", ".gitignore", ".gitattributes")
    _git(src, "commit", "--quiet", "-m", "init")
    (src / "ignored_dir").mkdir()
    (src / "ignored_dir" / "x.txt").write_text("x\n")

    dest = tmp_path / "dest"
    publish._export_head(src, dest)

    assert (dest / "tracked.txt").is_file()
    assert (dest / "secret.txt").is_file()
    assert not (dest / "ignored_dir").exists()
    assert _git(dest, "rev-parse", "--is-inside-work-tree") == "true"
    assert _git(dest, "rev-parse", "HEAD") == _git(src, "rev-parse", "HEAD")
