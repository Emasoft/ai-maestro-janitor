"""doctor `_check_gitignore_reports` (TRDD-KSUIEPTQ): PASS iff reports_dev/ is ignored AND
reports/ is NOT — asked of git, with the machine's global excludes pinned out."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import state  # noqa: E402

_spec = importlib.util.spec_from_file_location("doctor_under_test", _ROOT / "scripts" / "commands" / "doctor.py")
assert _spec and _spec.loader
doctor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(doctor)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    monkeypatch.setattr(state, "project_root", lambda: root)
    return root


def _status(repo: Path, gitignore: str) -> str:
    (repo / ".gitignore").write_text(gitignore, encoding="utf-8")
    return doctor._check_gitignore_reports()[1]


def test_pass_when_reports_dev_ignored_and_reports_tracked(repo: Path) -> None:
    """The new rule: raw dir ignored, tracked dir not."""
    assert _status(repo, "/reports_dev/\n") == "PASS"


def test_fail_when_reports_dev_is_not_ignored(repo: Path) -> None:
    """Raw reports may carry private data."""
    assert _status(repo, "*.log\n") == "FAIL"


def test_fail_when_reports_is_ignored(repo: Path) -> None:
    """reports/ is tracked project content; ignoring it is the old mistake."""
    assert _status(repo, "/reports/\n/reports_dev/\n") == "FAIL"
