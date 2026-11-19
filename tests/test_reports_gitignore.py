"""The reports_dev/ gitignore invariant (TRDD-KSUIEPTQ).

`reports_dev/` holds raw reports (absolute home paths, usernames, credentials caught in logs) and
must be gitignored. `reports/` is git-tracked project content: the janitor must never add it to
`.gitignore`, and must never edit or remove an existing `/reports/` line (that would expose
reports written under the old private regime as untracked files).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from exe_path import exe

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import reports_gitignore as rg  # noqa: E402

_HEADER = rg._BLOCK_HEADER


@pytest.fixture(autouse=True)
def _isolated_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`git check-ignore` reads the machine's global excludes; pin it so no test here can pass
    or fail by machine."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run([exe("git"), "init", "-q"], cwd=root, check=True)
    subprocess.run([exe("git"), "config", "user.name", "t"], cwd=root, check=True)
    subprocess.run([exe("git"), "config", "user.email", "t@e"], cwd=root, check=True)
    (root / "f.txt").write_text("x", encoding="utf-8")
    subprocess.run([exe("git"), "add", "f.txt"], cwd=root, check=True)
    subprocess.run([exe("git"), "commit", "-qm", "init"], cwd=root, check=True)
    return root


def test_only_reports_dev_is_required() -> None:
    """reports/ is tracked project content; only the raw dir may be required-ignored."""
    assert rg.REQUIRED_DIRS == ("reports_dev",)


def test_missing_reports_dev_is_ADDED_and_reports_is_not(tmp_path):
    """One defensible answer to 'reports_dev is not ignored', so it is taken; reports/ is left."""
    root = _repo(tmp_path)
    added, ok, human = rg.ensure_ignored(root)
    assert added == ["reports_dev"] and not human
    assert rg.is_ignored(root, "reports_dev/x.md") is True
    assert rg.is_ignored(root, "reports/x.md") is False
    assert "/reports/" not in (root / ".gitignore").read_text(encoding="utf-8")


def test_it_is_idempotent(tmp_path):
    """A detector runs every cadence forever; a second pass must add nothing."""
    root = _repo(tmp_path)
    rg.ensure_ignored(root)
    before = (root / ".gitignore").read_text(encoding="utf-8")
    added, ok, _ = rg.ensure_ignored(root)
    assert added == [] and ok == ["reports_dev"]
    assert (root / ".gitignore").read_text(encoding="utf-8") == before


def test_an_existing_gitignore_is_APPENDED_never_rewritten(tmp_path):
    """The file is the user's and is hand-curated in every repo worth having one."""
    root = _repo(tmp_path)
    (root / ".gitignore").write_text("# mine\n*.log\n", encoding="utf-8")
    rg.ensure_ignored(root)
    text = (root / ".gitignore").read_text(encoding="utf-8")
    assert text.startswith("# mine\n*.log\n"), "existing content must survive verbatim"
    assert "/reports_dev/" in text


def test_an_existing_reports_ignore_line_is_never_edited(tmp_path):
    """A /reports/ line (the user's, or the janitor's old one) stays byte-identical: removing it
    would expose old private-regime reports as untracked files."""
    root = _repo(tmp_path)
    original = f"# mine\n/reports/\n\n{_HEADER}\n/reports/\n/reports_dev/\n"
    (root / ".gitignore").write_text(original, encoding="utf-8")
    added, ok, human = rg.ensure_ignored(root)
    assert added == [] and ok == ["reports_dev"] and not human
    assert (root / ".gitignore").read_text(encoding="utf-8") == original


def test_a_TRACKED_reports_dev_is_never_silently_ignored(tmp_path):
    """THE refusal. A gitignore line does not untrack an already-tracked file, so adding one
    would leave the repo still leaking while the finding disappears. Untracking has two
    defensible answers, so a human picks."""
    root = _repo(tmp_path)
    (root / "reports_dev").mkdir()
    (root / "reports_dev" / "leak.md").write_text("pasted log line\n", encoding="utf-8")
    subprocess.run([exe("git"), "add", "-f", "reports_dev/leak.md"], cwd=root, check=True)
    added, _ok, human = rg.ensure_ignored(root)
    assert "reports_dev" in human and "reports_dev" not in added
    assert not (root / ".gitignore").is_file()


def test_the_escalation_says_what_to_actually_do():
    """A finding that names no action is noise — and a public leak needs rotation."""
    msg = rg.format_finding(["reports_dev"])
    assert "git rm --cached" in msg
    assert "rotate" in msg.lower()
    assert rg.format_finding([]) == ""


def test_an_unanswerable_git_returns_None_and_changes_nothing(tmp_path):
    """'git failed' must not read as 'not ignored' — that would append duplicate lines."""
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    assert rg.is_ignored(plain, "reports_dev/x") is None
    assert rg.ensure_ignored(plain) == ([], [], [])
    assert not (plain / ".gitignore").exists()
