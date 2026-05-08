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

Dedup is keyed by HEAD SHA: this list cannot change without a git op
(commit, rm, ignore-edit), so we re-run the check at most once per HEAD
rather than once per heartbeat. Saves ~50ms per fire on large repos.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import state  # noqa: E402


def main() -> int:
    state.init_state()

    seen = state.state_dir() / "tracked-ignored-seen.txt"
    last_head_file = state.state_dir() / "tracked-ignored-last-head.ts"
    project_root = state.project_root()

    if subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=str(project_root),
        capture_output=True, text=True, check=False,
    ).returncode != 0:
        state.log_line("tracked-ignored", "not a git repo — skipping")
        return 0

    head_proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(project_root),
        capture_output=True, text=True, check=False,
    )
    if head_proc.returncode != 0:
        state.log_line("tracked-ignored", "no HEAD (empty repo?) — skipping")
        return 0
    head_sha = head_proc.stdout.strip()

    # If HEAD hasn't moved since last check, the answer can't have changed.
    if last_head_file.is_file():
        try:
            prev_head = last_head_file.read_text().strip()
        except OSError:
            prev_head = ""
        if prev_head == head_sha:
            return 0

    proc = subprocess.run(
        ["git", "ls-files", "--ignored", "--exclude-standard", "--cached"],
        cwd=str(project_root),
        capture_output=True, text=True, check=False,
    )
    # Stamp the HEAD as scanned regardless of result, so an empty answer
    # also gets cached and we don't re-shell `git ls-files` on the next
    # heartbeat.
    state.atomic_write(last_head_file, head_sha)
    if proc.returncode != 0:
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
    sample_lines = [f"  - {p}" for p in offenders[:10]]
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
