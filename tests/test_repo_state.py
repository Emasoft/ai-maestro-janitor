"""Tests for the repo-state detector (TRDD-DG2V7D5P).

The detector lives at scripts/detectors/repo-state.py. It reports (1) the
current branch's ahead/behind count against its upstream and (2) default-branch
commits newer than the newest `v*` release tag that were not made through
publish.py — publish.py's signature is the `chore: bump version to <semver>`
bump subject plus the `v<semver>` release tag.

Real git repos in temp dirs; no mocks.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

DETECTOR = Path(__file__).resolve().parent.parent / "scripts" / "detectors" / "repo-state.py"


def _load():
    spec = importlib.util.spec_from_file_location("repo_state_detector", DETECTOR)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["repo_state_detector"] = mod
    spec.loader.exec_module(mod)
    return mod


rs = _load()


# --------------------------------------------------------------------------- #
# fixture helpers — a real repo with a real `origin` (a local bare clone)
# --------------------------------------------------------------------------- #


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _commit(repo: Path, msg: str, filename: str = "f.txt") -> None:
    (repo / filename).write_text(msg, encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-qm", msg)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A work repo cloned from a local bare `origin`, one release already published."""
    work = tmp_path / "work"
    origin = tmp_path / "origin.git"
    # cwd=tmp_path on every git call whose cwd would otherwise be the project
    # root: the sandbox guard reads the CALLING cwd, and `git init` invoked
    # from the project tree reads as a mutation of the real repo.
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, capture_output=True, cwd=tmp_path)
    # A fresh bare repo's HEAD points at refs/heads/master, so a later
    # `git push origin HEAD:refs/heads/main` from a clone is rejected as
    # non-fast-forward against a ref that does not even exist. Point HEAD at
    # main BEFORE cloning so the work clone starts on `main`.
    subprocess.run(
        ["git", "-C", str(origin), "symbolic-ref", "HEAD", "refs/heads/main"],
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True, capture_output=True, cwd=tmp_path)
    _git(work, "config", "user.email", "t@t.t")
    _git(work, "config", "user.name", "t")

    _commit(work, "seed")
    _commit(work, "chore: bump version to 1.2.3")
    _git(work, "tag", "v1.2.3")
    _git(work, "push", "-q", "origin", "HEAD:refs/heads/main")
    _git(work, "push", "-q", "origin", "v1.2.3")
    _git(work, "branch", "--set-upstream-to=origin/main")
    return work


def _run(project: Path, home: Path) -> str:
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["CLAUDE_PROJECT_DIR"] = str(project)
    res = subprocess.run([sys.executable, str(DETECTOR)], capture_output=True, text=True, env=env, timeout=60)
    assert res.returncode == 0, res.stderr
    return res.stdout


# --------------------------------------------------------------------------- #
# ahead / behind
# --------------------------------------------------------------------------- #


def test_ahead_count_after_local_commit(repo: Path, tmp_path: Path) -> None:
    _commit(repo, "local work one")
    _commit(repo, "local work two")

    out = _run(repo, tmp_path / "home1")

    assert "2 commit(s) ahead" in out


def test_behind_count_after_remote_commit(repo: Path, tmp_path: Path) -> None:
    # Push a commit from a second clone, then fetch: local is now behind.
    other = repo.parent / "other"
    subprocess.run(["git", "clone", "-q", repo.parent / "origin.git", str(other)], check=True, capture_output=True, cwd=tmp_path)
    _git(other, "config", "user.email", "t@t.t")
    _git(other, "config", "user.name", "t")
    _commit(other, "remote side work")
    _git(other, "push", "-q", "origin", "HEAD:refs/heads/main")
    _git(repo, "fetch", "-q", "origin")

    out = _run(repo, tmp_path / "home2")

    assert "1 behind" in out


def test_synced_branch_is_silent(repo: Path, tmp_path: Path) -> None:
    assert _run(repo, tmp_path / "home3") == ""


def test_no_upstream_is_silent(tmp_path: Path) -> None:
    """A repo with no upstream at all (local init, no remote) must not error or nag."""
    solo = tmp_path / "solo"
    solo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=solo, check=True, capture_output=True)
    _git(solo, "config", "user.email", "t@t.t")
    _git(solo, "config", "user.name", "t")
    _commit(solo, "seed")

    assert _run(solo, tmp_path / "home4") == ""


# --------------------------------------------------------------------------- #
# outside-publish detection
# --------------------------------------------------------------------------- #


def test_outside_publish_commit_is_flagged(repo: Path, tmp_path: Path) -> None:
    _commit(repo, "feat: sneaky direct commit")

    out = _run(repo, tmp_path / "home5")

    assert "NOT" in out and "publish.py" in out
    assert "feat: sneaky direct commit" in out


def test_publish_bump_commit_is_silent(repo: Path, tmp_path: Path) -> None:
    """A commit whose subject is publish.py's exact bump signature is not flagged."""
    _commit(repo, "chore: bump version to 1.3.0")

    out = _run(repo, tmp_path / "home6")

    assert "NOT" not in out, f"bump-subject commit flagged as outside-publish: {out!r}"


def test_new_release_tag_resets_the_count(repo: Path, tmp_path: Path) -> None:
    """After a real release (tag pushed), commits older than the new tag are no longer reported."""
    _commit(repo, "feat: sneaky direct commit")
    _commit(repo, "chore: bump version to 1.3.0")
    _git(repo, "tag", "v1.3.0")

    out = _run(repo, tmp_path / "home7")

    assert "NOT" not in out, f"released commit still flagged: {out!r}"


# --------------------------------------------------------------------------- #
# the pure helpers, pinned directly
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "subject,expected",
    [
        ("chore: bump version to 3.6.3", True),
        ("chore: bump version to 10.20.30", True),
        ("chore: bump version to 1.2", False),  # not a full semver
        ("chore: bump version to 1.2.3 extra", False),  # trailing text = a human's commit
        ("feat: bump version to 1.2.3", False),  # wrong prefix
        ("docs(TRDD): a normal commit", False),
    ],
)
def test_bump_subject_regex(subject: str, expected: bool) -> None:
    assert bool(rs._BUMP_SUBJECT.match(subject)) is expected


def test_tag_regex_matches_semver_tags_only() -> None:
    assert rs._TAG_NAME.match("v1.2.3")
    assert not rs._TAG_NAME.match("v1.2.3-rc1")  # publish.py never creates these, stay conservative
    assert not rs._TAG_NAME.match("not-a-release")
