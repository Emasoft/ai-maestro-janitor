#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Tracked-ignored detector — Python port of tracked-ignored.sh.

Surfaces files that are CURRENTLY tracked by git but ALSO match a rule
in the active `.gitignore`. These typically arrive when a `.gitignore`
rule is added AFTER the file was committed: git keeps tracking the file
(existing entries survive ignore changes by design), while the rule
misleads the user into thinking the file is excluded.

`git ls-files --ignored --exclude-standard --cached` produces this list
directly. Common offenders: `.env` committed before the rule was added,
build artifacts (`dist/`, `*.pyc`), IDE files (`.idea/`, `.vscode/`),
OS noise (`.DS_Store`).

Dedup is keyed by HEAD SHA + the mtimes of the active ignore files
(`.gitignore` and `.git/info/exclude`). HEAD-only caching was wrong:
adding a rule to `.gitignore` without committing it changes the answer
without moving HEAD, so the previous version served stale results until
the next commit. Mixing the ignore-file mtimes flushes the cache the
moment the rules change.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import state  # noqa: E402


def _cache_key(project_root: Path, head_sha: str) -> str:
    """Compose the staleness key from HEAD + ignore-file mtimes.

    Adding `/foo` to `.gitignore` (uncommitted) changes the answer of
    `git ls-files -i -c --exclude-standard` without moving HEAD. Keying
    on HEAD alone misses every such edit until the next commit. Mixing
    the mtimes of the project-root `.gitignore` and `.git/info/exclude`
    (the two files git's `--exclude-standard` consumes) makes the cache
    invalidate the moment either changes.

    Missing files contribute mtime=0 — a project with no `.gitignore`
    still gets a stable key from HEAD alone. We don't try to recurse
    into nested `.gitignore` files because those don't affect the
    tracked-ignored set unless a previously-tracked file's path now
    matches a deeper rule, which is uncommon and not worth the walk.
    """
    gi_mtime = state.file_mtime(project_root / ".gitignore")
    excl_mtime = state.file_mtime(project_root / ".git" / "info" / "exclude")
    return f"{head_sha}@gi{gi_mtime}@ex{excl_mtime}"


def main() -> int:
    state.init_state()

    seen = state.state_dir() / "tracked-ignored-seen.txt"
    last_key_file = state.state_dir() / "tracked-ignored-last-head.ts"
    project_root = state.project_root()

    git_dir_proc = state.run_subprocess(
        ["git", "rev-parse", "--git-dir"],
        cwd=project_root,
        timeout=5,
        detector_name="tracked-ignored",
    )
    if git_dir_proc is None or git_dir_proc.returncode != 0:
        state.log_line("tracked-ignored", "not a git repo — skipping")
        return 0

    head_proc = state.run_subprocess(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        timeout=5,
        detector_name="tracked-ignored",
    )
    if head_proc is None or head_proc.returncode != 0:
        state.log_line("tracked-ignored", "no HEAD (empty repo?) — skipping")
        return 0
    head_sha = head_proc.stdout.strip()
    cache_key = _cache_key(project_root, head_sha)

    # If neither HEAD nor any ignore file has changed since last check,
    # the answer can't have changed either.
    if last_key_file.is_file():
        try:
            prev_key = last_key_file.read_text().strip()
        except OSError:
            prev_key = ""
        if prev_key == cache_key:
            return 0

    proc = state.run_subprocess(
        ["git", "ls-files", "--ignored", "--exclude-standard", "--cached"],
        cwd=project_root,
        timeout=15,
        detector_name="tracked-ignored",
    )
    # Stamp the cache key as scanned regardless of result, so an empty
    # answer also gets cached and we don't re-shell `git ls-files` on
    # the next heartbeat. We stamp BEFORE checking returncode so a
    # transient failure (e.g. .git/index lock) still cached the previous
    # SHA-only key — instead, stamping first ensures a clean re-run on
    # the next fire if the ls-files call genuinely failed.
    state.atomic_write(last_key_file, cache_key)
    if proc is None or proc.returncode != 0:
        state.log_line("tracked-ignored", "git ls-files failed — skipping")
        return 0

    offenders = [line for line in proc.stdout.splitlines() if line]
    if not offenders:
        return 0

    # Cap the displayed list to avoid drowning the model in a 200-line
    # nudge for projects that committed an entire `node_modules/`. Show
    # the count and the first 10; the user can run
    # `git ls-files -i -c -X .gitignore` to see the full set.
    count = len(offenders)
    # Defense-in-depth: filenames are paths from `git ls-files` so they
    # SHOULD be plain strings, but git's index can technically hold
    # filenames with `[`/`]` and control chars. Sanitize before printing.
    sample_lines = [f"  - {state.sanitize_for_drift_line(p)}" for p in offenders[:10]]
    if count > 10:
        sample_lines.append(f"  - …and {count - 10} more")
    sample = "\n".join(sample_lines)

    line = dedupe.emit_once(
        seen,
        f"trackedignored@{head_sha}",
        f"[tracked-ignored] {count} tracked file(s) match current .gitignore rules — they were committed "
        f"before the rule was added and git keeps tracking them. Stop tracking with: "
        f"git rm --cached -r -- <path> (then commit). Affected:\n{sample}",
    )
    if line is not None:
        print(line)

    state.rotate_log_if_big("tracked-ignored")
    return 0


if __name__ == "__main__":
    sys.exit(main())
