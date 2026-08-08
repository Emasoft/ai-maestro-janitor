#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Nested-git-safety detector — Python port of nested-git-safety.sh.

Finds nested `.git` directories that are NOT excluded by the parent's
gitignore. An unignored nested `.git` is a real corruption hazard:
  * `git add .` from the parent can stage the inner `.git/objects/...`
    blobs as ordinary files, polluting the parent index.
  * Cloning the parent recursively lands the inner repo as flat
    directories (no submodule pointer), silently breaking the inner
    repo's history.

The fix is mechanical: add the nested directory (or `*/.git` glob) to
the parent's `.gitignore`. We surface the exact rule the user should add.

Performance: depth-limited (mindepth 2, maxdepth 4) and prunes the
.trashcan/, node_modules/, dist/, build/, .venv/, venv/ subtrees so a
large monorepo or a project with many vendored deps still finishes well
under the 10s budget.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import state  # noqa: E402


def _git_env() -> dict[str, str]:
    """Read-only detector: GIT_OPTIONAL_LOCKS=0 so `rev-parse`/`check-ignore`/
    `submodule status` never take .git/index.lock and collide with a
    concurrent `publish.py` commit (janitor#245)."""
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return env

_PRUNE_NAMES = {".git", ".trashcan", "node_modules", "dist", "build", ".venv", "venv"}
_MIN_DEPTH = 2
_MAX_DEPTH = 4


def _walk_for_nested_git(root: Path) -> list[Path]:
    """Yield .git entries (file or dir) under `root`, depth-limited and pruned.

    Returns paths RELATIVE to root. Mirrors the bash port's `find` invocation:
    skip the prune set at any level, only emit at depth >= 2, stop at depth 4.
    """
    found: list[Path] = []

    def walk(current: Path, depth: int) -> None:
        if depth > _MAX_DEPTH:
            return
        try:
            entries = list(current.iterdir())
        except (OSError, PermissionError):
            return
        for entry in entries:
            name = entry.name
            if name in _PRUNE_NAMES:
                # Found a prune candidate. Emit it as a hit only if it's
                # actually `.git` AND we're at min depth or deeper.
                if name == ".git" and depth >= _MIN_DEPTH:
                    found.append(entry)
                continue  # never descend into pruned subtrees
            if entry.is_dir():
                walk(entry, depth + 1)

    walk(root, 1)
    return found


def main() -> int:
    state.init_state()

    seen = state.state_dir() / "nested-git-safety-seen.txt"
    root = state.project_root()

    git_env = _git_env()

    if subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=str(root),
        capture_output=True, text=True, check=False,
        env=git_env,
    ).returncode != 0:
        state.log_line("nested-git-safety", "not a git repo — skipping")
        return 0

    nested = _walk_for_nested_git(root)
    for nested_git in nested:
        rel = nested_git.relative_to(root)
        # rel should look like vendor/lib/.git
        rel_str = str(rel)
        if not rel_str.endswith("/.git") and rel_str != ".git":
            continue
        if rel_str == ".git":
            continue  # the parent's own .git — never flag
        parent_dir = rel_str[:-len("/.git")]
        if not parent_dir or parent_dir == rel_str:
            continue

        # `git check-ignore -q` exits 0 when the path IS ignored. We want
        # 'not ignored' → emit nudge.
        if subprocess.run(
            ["git", "check-ignore", "-q", "--", parent_dir],
            cwd=str(root),
            capture_output=True, text=True, check=False,
            env=git_env,
        ).returncode == 0:
            continue
        if subprocess.run(
            ["git", "check-ignore", "-q", "--", rel_str],
            cwd=str(root),
            capture_output=True, text=True, check=False,
            env=git_env,
        ).returncode == 0:
            continue

        # Skip if parent_dir is actually tracked as a submodule.
        if subprocess.run(
            ["git", "submodule", "status", "--", parent_dir],
            cwd=str(root),
            capture_output=True, text=True, check=False,
            env=git_env,
        ).returncode == 0:
            continue

        # `safe_parent` quotes the path for use as a SHELL ARGUMENT (e.g.
        # in `git submodule add <url> <path>`). For the .gitignore line
        # itself we describe the LITERAL text the user should add —
        # wrapping the path in backticks for visual clarity but
        # deliberately NOT embedding it inside a shell `echo '...' >>`
        # snippet. A path like `weird'name/` would break naive
        # `echo '...'` quoting on copy-paste; describing the line plainly
        # avoids that injection vector while still being actionable.
        safe_parent = shlex.quote(parent_dir)
        # Sanitize the path for the human-readable / .gitignore-text part
        # of the message — defangs `[`/`]` so a directory name like
        # `[janitor-resume]` cannot mimic our marker convention. The
        # `safe_parent` form (shell-quoted) stays untouched so the
        # `git submodule add` snippet remains paste-and-run safe.
        display_parent = state.sanitize_for_drift_line(parent_dir)

        line = dedupe.emit_once(
            seen,
            f"nestedgit@{parent_dir}",
            f"[nested-git-safety] URGENT: nested git repo at {display_parent}/ is NOT in .gitignore. "
            f"A 'git add .' from the project root can stage the inner .git contents and corrupt both repos. "
            f"Fix: append the literal line `/{display_parent}/` to .gitignore, OR convert the directory into a "
            f"real submodule with: git submodule add <url> {safe_parent}",
        )
        if line is not None:
            print(line)

    state.rotate_log_if_big("nested-git-safety")
    return 0


if __name__ == "__main__":
    sys.exit(main())
