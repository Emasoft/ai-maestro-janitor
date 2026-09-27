#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Repo-state detector (TRDD-DG2V7D5P) — reports branch ahead/behind origin and
unreleased commits on the default branch.

Nothing computed ahead/behind before this: main sat 157 commits past the last
release on 2026-09-24 and no detector noticed. Two findings, both advisory:

1. ahead/behind: the current branch vs its upstream. Behind means a stale
   checkout; ahead means unpublished work. Skipped entirely when no upstream
   is configured (fresh local repo, or a repo cloned without an origin).
2. outside-publish commits: default-branch commits newer than the newest
   `v*` release tag. publish.py marks a release two ways — it creates the
   version-bump commit with subject exactly `chore: bump version to <semver>`
   and tags the release `v<semver>`. So "made through publish.py" resolves to
   (reachable from a v* tag) OR (subject is the bump subject); anything else
   newer than the newest v* tag is unreleased work that never went through the
   publish gate. Deliberately conservative: an ordinary commit made BETWEEN
   releases is normal workflow, so this reports an informational count rather
   than an alarm, and dedupes on (tag, count) so the same state does not
   re-nag every hour.

Read-only on the repo: every git call runs with GIT_OPTIONAL_LOCKS=0 so it
never takes .git/index.lock and cannot collide with a concurrent publish.py
commit (janitor#245, the named repro site).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Locate scripts/lib relative to this file so the detector works regardless
# of the user's cwd. The same idiom is reused by every Python detector.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import state  # noqa: E402

# publish.py's own version-bump subject (scripts/publish.py: expected_subject
# = f"chore: bump version to {new_ver}"). A commit whose subject matches this
# was made by the publish pipeline, even before its release tag exists.
_BUMP_SUBJECT = re.compile(r"^chore: bump version to \d+\.\d+\.\d+$")

# A release tag: publish.py creates exactly `v<semver>` (tag = f"v{new_ver}").
# The capture groups are parsed for semver ordering in _last_release_tag.
_TAG_NAME = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def _git_env() -> dict[str, str]:
    # GIT_OPTIONAL_LOCKS=0 — see module docstring (janitor#245).
    git_env = dict(os.environ)
    git_env["GIT_OPTIONAL_LOCKS"] = "0"
    return git_env


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    """Run a read-only git command in `repo`; None only if git itself is missing."""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
            env=_git_env(),
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _resolve_repo(project_root: Path) -> Path | None:
    """The repo to report on: the project root, or its tracked-repo delegate."""
    proc = _git(project_root, "rev-parse", "--git-dir")
    if proc is not None and proc.returncode == 0:
        return project_root
    tracked = state.tracked_repo(str(project_root))
    return tracked


def _ahead_behind(repo: Path, branch: str) -> tuple[int, int] | None:
    """(behind, ahead) of the branch's upstream, or None when no upstream exists."""
    proc = _git(repo, "rev-list", "--left-right", "--count", f"{branch}@{{upstream}}...{branch}")
    if proc is None or proc.returncode != 0:
        # No upstream configured (or branch has none) — an informational skip,
        # not an error: fresh local repos and detached checkouts are normal.
        return None
    try:
        behind_s, ahead_s = proc.stdout.split()
        return int(behind_s), int(ahead_s)
    except ValueError:
        return None


def _current_branch(repo: Path) -> str | None:
    proc = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if proc is None or proc.returncode != 0:
        return None
    branch = proc.stdout.strip()
    return branch or None  # "HEAD" when detached — still reportable


def _last_release_tag(repo: Path) -> str | None:
    """Newest `v<semver>` tag, or None.

    Order by PARSED semver, never by `--sort=-creatordate`: two tags created
    within the same clock second (a fast publish, or a test fixture) tie on
    creatordate and git's refname tiebreak is ASCENDING, so the OLDER tag
    wins and the detector reports already-released commits as unreleased.

    Peel with `^{commit}` like publish.py does (`_rev_parse_commit`): an
    annotated tag's own sha is the tag OBJECT's, not the commit's, and
    comparing it into rev-list ranges silently excludes the released commit.
    """
    proc = _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/tags/")
    if proc is None or proc.returncode != 0:
        return None
    best: tuple[tuple[int, int, int], str] | None = None
    for name in proc.stdout.splitlines():
        name = name.strip()
        m = _TAG_NAME.match(name)
        if not m:
            continue
        peel = _git(repo, "rev-parse", "--verify", f"{name}^{{commit}}")
        if peel is None or peel.returncode != 0:
            continue
        ver = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if best is None or ver > best[0]:
            best = (ver, name)
    return best[1] if best else None


def _unreleased_subjects(repo: Path, tag: str, branch: str) -> list[str]:
    """Subjects on `branch` newer than `tag`, in oldest-first order."""
    proc = _git(repo, "log", "--format=%s", "--reverse", f"{tag}..{branch}")
    if proc is None or proc.returncode != 0:
        return []
    return [line for line in proc.stdout.splitlines() if line.strip()]


def main() -> int:
    state.init_state()

    repo = _resolve_repo(state.project_root())
    if repo is None:
        state.log_line("repo-state", "project root is not a git repo and no .janitor/track-repo is registered — skipping")
        return 0

    seen = state.state_dir() / "repo-state-seen.txt"
    now = int(time.time())
    lines: list[str] = []

    branch = _current_branch(repo)
    if branch is not None:
        counts = _ahead_behind(repo, branch)
        if counts is not None:
            behind, ahead = counts
            if ahead or behind:
                key = f"ab@{branch}@{behind}@{ahead}"
                msg = f"[repo-state] Branch {branch} is {ahead} commit(s) ahead and {behind} behind its upstream. Publish unreleased work through scripts/publish.py, or pull to update a stale checkout."
                line = dedupe.emit_once(seen, key, msg)
                if line:
                    lines.append(line)

        tag = _last_release_tag(repo)
        if tag is not None:
            subjects = _unreleased_subjects(repo, tag, branch)
            outside = [s for s in subjects if not _BUMP_SUBJECT.match(s)]
            if outside:
                key = f"outside@{tag}@{len(outside)}@{now // 86400}"
                preview = "; ".join(outside[-3:])
                msg = f"[repo-state] {len(outside)} commit(s) on {branch} since release {tag} were NOT made through publish.py (neither release-tagged nor a 'chore: bump version to x.y.z' bump): {preview}. Run scripts/publish.py to cut a release."
                line = dedupe.emit_once(seen, key, msg)
                if line:
                    lines.append(line)

    for line in lines:
        print(line)
    if lines:
        state.rotate_log_if_big("repo-state")
    return 0


if __name__ == "__main__":
    # `--one-shot` is the historical flag from the bash port. We accept it
    # as a no-op for backward compatibility — every Python detector is
    # one-shot by construction (no daemon mode).
    sys.exit(main())
