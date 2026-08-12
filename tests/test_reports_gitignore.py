"""The reports/ gitignore invariant — check AND fix (TRDD-WP7TCRME Rule 3).

Reports carry absolute home paths, usernames, hostnames and credentials caught in pasted logs.
Committing one to a public repo is irreversible: `git rm` does not remove it from history, from
forks, or from whatever already mirrored it. So these tests pin the fix AND, more importantly,
the one case it must refuse to touch.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import reports_gitignore as rg  # noqa: E402


def _repo(tmp_path: Path) -> Path:
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e", "PATH": "/usr/bin:/bin"}
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, env=env)
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "f.txt"], cwd=tmp_path, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True, env=env)
    return tmp_path


def test_missing_entries_are_ADDED_not_reported(tmp_path):
    """One defensible answer to 'your report directory is not ignored', so it is taken."""
    root = _repo(tmp_path)
    added, ok, human = rg.ensure_ignored(root)
    assert sorted(added) == ["reports", "reports_dev"]
    assert not human
    assert rg.is_ignored(root, "reports/x.md") is True
    assert rg.is_ignored(root, "reports_dev/x.md") is True


def test_it_is_idempotent(tmp_path):
    """A detector runs every cadence forever; a second pass must add nothing."""
    root = _repo(tmp_path)
    rg.ensure_ignored(root)
    before = (root / ".gitignore").read_text(encoding="utf-8")
    added, ok, _ = rg.ensure_ignored(root)
    assert added == [] and sorted(ok) == ["reports", "reports_dev"]
    assert (root / ".gitignore").read_text(encoding="utf-8") == before


def test_an_existing_gitignore_is_APPENDED_never_rewritten(tmp_path):
    """The file is the user's and is hand-curated in every repo worth having one."""
    root = _repo(tmp_path)
    (root / ".gitignore").write_text("# mine\n*.log\n", encoding="utf-8")
    rg.ensure_ignored(root)
    text = (root / ".gitignore").read_text(encoding="utf-8")
    assert text.startswith("# mine\n*.log\n"), "existing content must survive verbatim"
    assert "/reports/" in text


def test_a_TRACKED_report_dir_is_never_silently_ignored(tmp_path):
    """THE refusal. A gitignore line does not untrack an already-tracked file, so adding one
    would leave the repo still leaking while the finding disappears — silencing a warning
    without fixing the thing is worse than the warning. Untracking has two defensible answers,
    so a human picks."""
    root = _repo(tmp_path)
    (root / "reports").mkdir()
    (root / "reports" / "leak.md").write_text("/Users/someone/secret\n", encoding="utf-8")
    subprocess.run(["git", "add", "-f", "reports/leak.md"], cwd=root, check=True,
                   env={"PATH": "/usr/bin:/bin"})
    added, _ok, human = rg.ensure_ignored(root)
    assert "reports" in human, "a tracked report dir must be escalated, not auto-ignored"
    assert "reports" not in added
    assert "/reports/" not in (root / ".gitignore").read_text(encoding="utf-8") \
        if (root / ".gitignore").is_file() else True


def test_the_escalation_says_what_to_actually_do(tmp_path):
    """A finding that names no action is the noise this whole card exists to remove — and this
    one must say that a public leak needs rotation, not just untracking."""
    msg = rg.format_finding(["reports"])
    assert "git rm --cached" in msg
    assert "rotate" in msg.lower()
    assert rg.format_finding([]) == ""


def test_an_unanswerable_git_returns_None_and_changes_nothing(tmp_path):
    """'git failed' must not read as 'not ignored' — that would append duplicate lines to a
    file that may already be correct, on every fire."""
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert rg.is_ignored(plain, "reports/x") is None
    assert rg.ensure_ignored(plain) == ([], [], [])
    assert not (plain / ".gitignore").exists()
