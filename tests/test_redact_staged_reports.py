"""Tests for scripts/lib/redact_staged_reports.py, pre-commit Stage 0 (TRDD-KSUIEPTQ).

OWNER ORDER 2026-11-14: reports/ is git-tracked and the secret redactor runs
before every commit, redacting the new files under reports/. Real git repos in
tmp_path and the REAL `sanitize-reports` CLI, no mocks. If the CLI is missing
the tests FAIL (never skip): a missing redactor is exactly the condition the
helper must refuse to commit through.
"""

from __future__ import annotations

import getpass
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_HELPER = Path(__file__).resolve().parent.parent / "scripts" / "lib" / "redact_staged_reports.py"

# Assembled at runtime: this file is tracked and scanned by the privacy gate.
_HOME_PATH = "/Users/" + getpass.getuser() + "/proj/f"


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=True, timeout=30,
    )
    return r.stdout


def _run_helper(repo: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_HELPER)],
        cwd=str(repo), capture_output=True, text=True, timeout=60, env=env,
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A real git repo with one clean base commit; sanitize-reports must exist."""
    assert shutil.which("sanitize-reports"), "sanitize-reports CLI is required on PATH"
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@example.invalid")
    _git(r, "config", "user.name", "t")
    (r / "notes.txt").write_text("line1\n", encoding="utf-8")
    _git(r, "add", "notes.txt")
    _git(r, "commit", "-q", "-m", "base")
    return r


def _stage(repo: Path, name: str, text: str) -> None:
    target = repo / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    _git(repo, "add", name)


@pytest.mark.real_subprocess("sanitize-reports", "scutil", "bun")  # sanitize-reports reads the host name via scutil; since report-sanitizer merged the secret shield it runs the shield core in bun (TRDD-NRF7OJ5H)
def test_staged_reports_file_is_redacted_in_the_index(repo: Path) -> None:
    """A home path in a staged reports/ file is gone from the staged blob afterwards."""
    _stage(repo, "reports/x.md", f"see {_HOME_PATH} here\n")
    r = _run_helper(repo)
    assert r.returncode == 0, r.stderr
    assert _HOME_PATH not in _git(repo, "show", ":reports/x.md")
    assert "redacted 1 staged reports/ file(s), 1 replacements" in r.stdout
    assert _git(repo, "diff", "--name-only") == ""


def test_missing_sanitize_reports_fails_closed(repo: Path) -> None:
    """With sanitize-reports off PATH and a staged reports/ file the helper exits 1."""
    _stage(repo, "reports/x.md", f"see {_HOME_PATH} here\n")
    git_dir = str(Path(shutil.which("git") or "").parent)
    env = {**os.environ, "PATH": git_dir}
    assert shutil.which("sanitize-reports", path=git_dir) is None, "test PATH must hide the CLI"
    r = _run_helper(repo, env=env)
    assert r.returncode == 1
    assert "sanitize-reports" in r.stderr
    assert _HOME_PATH in _git(repo, "show", ":reports/x.md")


def test_unstaged_hunks_in_reports_file_fail_closed(repo: Path) -> None:
    """A reports/ file with unstaged changes makes the helper exit 1 and leave the index alone."""
    _stage(repo, "reports/x.md", f"see {_HOME_PATH} here\n")
    (repo / "reports" / "x.md").write_text(f"see {_HOME_PATH} here\nmore\n", encoding="utf-8")
    before = _git(repo, "ls-files", "-s")
    r = _run_helper(repo)
    assert r.returncode == 1
    assert "unstaged" in r.stderr
    assert _git(repo, "ls-files", "-s") == before


def test_no_reports_files_staged_is_silent_success(repo: Path) -> None:
    """Staged files only outside reports/ give exit 0 and no output."""
    _stage(repo, "docs/a.md", f"see {_HOME_PATH} here\n")
    r = _run_helper(repo)
    assert r.returncode == 0
    assert r.stdout == ""
    assert r.stderr == ""
    assert _HOME_PATH in _git(repo, "show", ":docs/a.md")


@pytest.mark.real_subprocess("sanitize-reports", "scutil", "bun")  # sanitize-reports reads the host name via scutil; since report-sanitizer merged the secret shield it runs the shield core in bun (TRDD-NRF7OJ5H)
def test_reports_dev_file_is_never_touched(repo: Path) -> None:
    """A staged reports_dev/ file keeps its content while reports/ is redacted."""
    _stage(repo, "reports_dev/y.md", f"see {_HOME_PATH} here\n")
    _stage(repo, "reports/x.md", f"see {_HOME_PATH} here\n")
    r = _run_helper(repo)
    assert r.returncode == 0, r.stderr
    assert _HOME_PATH not in _git(repo, "show", ":reports/x.md")
    assert _HOME_PATH in _git(repo, "show", ":reports_dev/y.md")
    assert _HOME_PATH in (repo / "reports_dev" / "y.md").read_text(encoding="utf-8")
