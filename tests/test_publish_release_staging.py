"""Tests for publish.py's release-commit staging — the replacement for `git add -A`.

THE INCIDENT THIS EXISTS FOR (2026-07-28). Step 1 of the pipeline refuses to run
unless `git status --porcelain` is empty, and step 10 commits the version bump about
ten minutes later — the lint, the full pytest suite, the remote CPV validate and the
CI-parity preflight all happen in between. `git add -A` at step 10 therefore swept
whatever appeared during that window into a commit titled "chore: bump version to
X.Y.Z" that nobody reads. It nearly happened: two memory pages edited while the suite
ran were one `git add -A` away from shipping inside a release commit, and an agent
report or a leaked test scratch file would have gone the same way — reports routinely
carry absolute paths and private data.

So the staging list is now ENUMERATED, and anything else that is dirty is a refusal,
not a silent inclusion. These tests build REAL git repositories in tmp_path and run
REAL `git` — no mocks, because the whole behaviour under test is what `git status
--porcelain` prints for renames, untracked files, and quoted paths.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import publish  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=True, timeout=30,
    )
    return r.stdout


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A real git repo with a committed baseline of real release artifacts."""
    r = tmp_path / "repo"
    (r / ".claude-plugin").mkdir(parents=True)
    _git(r.parent, "init", "-q", "repo")
    _git(r, "config", "user.email", "t@example.invalid")
    _git(r, "config", "user.name", "t")
    (r / ".claude-plugin" / "plugin.json").write_text('{"version": "1.0.0"}\n', encoding="utf-8")
    (r / "pyproject.toml").write_text('version = "1.0.0"\n', encoding="utf-8")
    (r / "README.md").write_text("badge 1.0.0\n", encoding="utf-8")
    (r / "notes.md").write_text("untouched\n", encoding="utf-8")
    (r / "scripts").mkdir()
    (r / "scripts" / "tool.py").write_text('__version__ = "1.0.0"\n\nX = 1\n', encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "baseline")
    return r


def test_a_clean_tree_yields_nothing_to_stage_and_nothing_to_refuse(repo: Path) -> None:
    """A clean tree produces two empty lists, so the caller refuses rather than committing."""
    assert publish._release_paths(repo) == ([], [])


def test_bumped_release_artifacts_are_the_staging_list(repo: Path) -> None:
    """The files a version bump legitimately rewrites are the ones staged."""
    (repo / ".claude-plugin" / "plugin.json").write_text('{"version": "1.1.0"}\n', encoding="utf-8")
    (repo / "pyproject.toml").write_text('version = "1.1.0"\n', encoding="utf-8")
    (repo / "README.md").write_text("badge 1.1.0\n", encoding="utf-8")
    (repo / "CHANGELOG.md").write_text("## 1.1.0\n", encoding="utf-8")

    artifacts, unexpected = publish._release_paths(repo)

    assert unexpected == []
    assert sorted(artifacts) == [
        ".claude-plugin/plugin.json", "CHANGELOG.md", "README.md", "pyproject.toml",
    ]


def test_an_unrelated_edit_made_while_the_suite_ran_is_refused_not_swept(repo: Path) -> None:
    """The regression: a file edited after step 1 must never ride into the release commit."""
    (repo / "pyproject.toml").write_text('version = "1.1.0"\n', encoding="utf-8")
    (repo / "notes.md").write_text("edited while pytest was running\n", encoding="utf-8")

    artifacts, unexpected = publish._release_paths(repo)

    assert artifacts == ["pyproject.toml"]
    assert unexpected == ["notes.md"]


def test_an_untracked_file_that_appeared_mid_run_is_refused(repo: Path) -> None:
    """A leaked test artifact or an agent report is untracked — and must still block."""
    (repo / "pyproject.toml").write_text('version = "1.1.0"\n', encoding="utf-8")
    (repo / "report-with-absolute-paths.md").write_text("/Users/someone/secret\n", encoding="utf-8")

    artifacts, unexpected = publish._release_paths(repo)

    assert artifacts == ["pyproject.toml"]
    assert unexpected == ["report-with-absolute-paths.md"]


def test_a_version_only_python_rewrite_is_a_release_artifact(repo: Path) -> None:
    """update_python_versions rewrites __version__ across scripts/ — that IS part of a bump."""
    (repo / "scripts" / "tool.py").write_text('__version__ = "1.1.0"\n\nX = 1\n', encoding="utf-8")

    artifacts, unexpected = publish._release_paths(repo)

    assert artifacts == ["scripts/tool.py"]
    assert unexpected == []


def test_the_same_python_file_carrying_a_real_code_change_is_refused(repo: Path) -> None:
    """Allowlisting the PATH would have shipped this; checking the DIFF is why it does not."""
    (repo / "scripts" / "tool.py").write_text(
        '__version__ = "1.1.0"\n\nX = 2\n', encoding="utf-8",
    )

    artifacts, unexpected = publish._release_paths(repo)

    assert artifacts == []
    assert unexpected == ["scripts/tool.py"]


def test_a_renamed_file_is_reported_by_its_new_path(repo: Path) -> None:
    """git prints "old -> new" for a rename; staging the raw string would fail the add."""
    _git(repo, "mv", "notes.md", "renamed-notes.md")

    artifacts, unexpected = publish._release_paths(repo)

    assert artifacts == []
    assert unexpected == ["renamed-notes.md"]


def test_a_path_with_a_space_is_returned_unquoted(repo: Path) -> None:
    """git quotes such paths in --porcelain; a quoted string would not match the allowlist."""
    (repo / "a file.md").write_text("x\n", encoding="utf-8")

    _artifacts, unexpected = publish._release_paths(repo)

    assert unexpected == ["a file.md"]


def test_every_staged_path_is_one_git_can_actually_add(repo: Path) -> None:
    """End-to-end: the list is fed to a REAL `git add`, proving the paths are usable."""
    (repo / "pyproject.toml").write_text('version = "1.1.0"\n', encoding="utf-8")
    (repo / "CHANGELOG.md").write_text("## 1.1.0\n", encoding="utf-8")

    artifacts, unexpected = publish._release_paths(repo)
    assert unexpected == []
    _git(repo, "add", "--", *artifacts)

    staged = _git(repo, "diff", "--cached", "--name-only").split()
    assert sorted(staged) == ["CHANGELOG.md", "pyproject.toml"]


def test_a_non_repo_directory_yields_empty_lists_so_the_caller_refuses(tmp_path: Path) -> None:
    """An unreadable status must never degrade into "stage everything"."""
    assert publish._release_paths(tmp_path) == ([], [])
