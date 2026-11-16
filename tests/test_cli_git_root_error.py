"""TRDD-7KPG2PCO: the three operator CLIs print one stderr line, not a traceback, when git fails resolving the design root."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
FINDINGS_CLI = SCRIPTS / "findings_cli.py"
TICKET_CLI = SCRIPTS / "ticket_cli.py"
FLEET_STATUS = SCRIPTS / "fleet_status.py"


def _project(tmp_path: Path) -> Path:
    """A temp git repo with a `.janitor` dir (so the fleet scan treats it as a janitor project)."""
    project = tmp_path / "proj"
    (project / "design" / "tasks").mkdir(parents=True)
    (project / ".janitor").mkdir()
    subprocess.run(["git", "init", "-q"], cwd=project, check=True, capture_output=True)
    return project


def _env(project: Path, failing_path: str) -> dict[str, str]:
    """Environment whose `git` fails `worktree list`; /usr/sbin is appended so `lsof` still resolves."""
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(project)
    env["CLAUDE_SESSION_ID"] = "abcdefab-cdef-4abc-8def-abcdefabcdef"
    env["PATH"] = f"{failing_path}:/usr/sbin:/sbin"
    env.pop("CLAUDE_PLUGIN_OPTION_TRDD_PATH", None)
    return env


def _assert_one_line(proc: subprocess.CompletedProcess[str], name: str, tmp_path: Path) -> None:
    """Exit 1, exactly one stderr line naming the CLI and the git failure, no traceback, no temp path."""
    assert proc.returncode == 1, proc.stderr
    assert "Traceback" not in proc.stderr, proc.stderr
    lines = [ln for ln in proc.stderr.splitlines() if ln.strip()]
    assert len(lines) == 1, proc.stderr
    assert lines[0].startswith(f"{name}:"), proc.stderr
    assert "git failed resolving the design root" in lines[0], proc.stderr
    assert str(tmp_path) not in proc.stderr, proc.stderr


@contextmanager
def _fake_claude_session(tmp_path: Path, project: Path) -> Iterator[None]:
    """A live process the fleet scan reads as a claude session (a `/share/claude/versions/` launcher path) with cwd `project`.

    Not named `claude`: the suite sandbox denies that binary name by default."""
    link_dir = tmp_path / "share" / "claude" / "versions"
    link_dir.mkdir(parents=True)
    link = link_dir / "2.0.0"
    shutil.copy("/bin/sleep", link)  # a tmp-resolved binary: the suite sandbox auto-allows it, a symlink to /bin/sleep it denies
    proc = subprocess.Popen([str(link), "300"], cwd=project)
    try:
        yield
    finally:
        proc.kill()
        proc.wait()


def test_findings_cli_show_reports_git_failure_in_one_line(tmp_path: Path, failing_worktree_list_git_path: str) -> None:
    """findings_cli `show TRDD-<id>` exits 1 with one stderr line when `git worktree list` fails."""
    project = _project(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(FINDINGS_CLI), "show", "TRDD-ABCDEFGH"],
        cwd=project, capture_output=True, text=True, env=_env(project, failing_worktree_list_git_path), timeout=60,
    )
    _assert_one_line(proc, "findings_cli", tmp_path)


def test_ticket_cli_proposals_reports_git_failure_in_one_line(tmp_path: Path, failing_worktree_list_git_path: str) -> None:
    """ticket_cli `proposals` exits 1 with one stderr line when `git worktree list` fails."""
    project = _project(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(TICKET_CLI), "proposals"],
        cwd=project, capture_output=True, text=True, env=_env(project, failing_worktree_list_git_path), timeout=60,
    )
    _assert_one_line(proc, "ticket_cli", tmp_path)


@pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("lsof", path="/usr/bin:/bin:/usr/sbin:/sbin") is None,
    reason="fleet_status end to end is checked on macOS only: its fleet probes (ps, lsof, osascript, tmux) were never run on Linux and the test asserts exactly one stderr line",
)
def test_fleet_status_reports_git_failure_in_one_line(tmp_path: Path, failing_worktree_list_git_path: str) -> None:
    """fleet_status exits 1 with one stderr line when `git worktree list` fails while gathering the kanban."""
    project = _project(tmp_path)
    with _fake_claude_session(tmp_path, project):
        proc = subprocess.run(
            [sys.executable, str(FLEET_STATUS), "--text", "--no-open"],
            cwd=project, capture_output=True, text=True, env=_env(project, failing_worktree_list_git_path), timeout=120,
        )
    _assert_one_line(proc, "fleet_status", tmp_path)
