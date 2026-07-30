#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Dirty-tree detector — Python port of dirty-tree.sh.

Nudges Claude Code to commit when the working tree has been dirty for
longer than the configured threshold. Frequent commits are the recovery
net: every commit is a restore point if a later change introduces a bug.
When the git safety guard blocks a destructive op, the right moves are:
move files to a `_dev/` folder, `git rm` to stage a recoverable deletion,
`git stash`, or stash+branch as a backup.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

# Locate scripts/lib relative to this file so the detector works regardless
# of the user's cwd. The same idiom is reused by every Python detector.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import state  # noqa: E402

# `git status --porcelain` line: 2 status chars, a space, then the path (`?? design/proposals/x.md`).
# A rename prints `old -> new`; we key on the NEW path, which is the one on disk.
_PROPOSAL_PREFIX = "design/proposals/"


def _is_janitor_proposal(status_line: str) -> bool:
    """True iff this dirty line is a proposal TRDD the JANITOR itself authored.

    The janitor is a GUEST in the user's repo: on a PROJECT-domain finding it may only PROPOSE,
    which means writing a TRDD into `design/proposals/` — and it is forbidden to commit that file,
    because running the approval command IS the approval. So the janitor creates a file it cannot
    clear, and this detector then counted it as the user's uncommitted work and nagged about it
    every window, forever. Observed on a real host: the same single item nagged from 443 to 487
    minutes, unclearable, while the ticket channel reported the SAME object as "awaiting your
    approval". One item, two unrelated-looking alarms, neither actionable by the reader.

    Reported by the Claude developing AgentlensPro, who diagnosed it exactly: *"the janitor's own
    proposals cause the dirty-tree nag, and neither can clear until you approve or refuse. It's a
    self-sustaining loop, not two problems."*

    Only `TRDD-*.md` directly under `design/proposals/` is excluded — a human's own edits anywhere
    else in that tree are still real dirty work, and the proposal itself is still surfaced, by the
    channel that can actually act on it.
    """
    path = status_line[3:] if len(status_line) > 3 else ""
    path = path.split(" -> ")[-1].strip().strip('"')
    if not path.startswith(_PROPOSAL_PREFIX):
        return False
    tail = path[len(_PROPOSAL_PREFIX) :]
    return "/" not in tail and tail.startswith("TRDD-") and tail.endswith(".md")


def main() -> int:
    state.init_state()

    seen = state.state_dir() / "dirty-tree-seen.txt"
    dirty_since = state.state_dir() / "dirty-tree-since.ts"
    threshold = state.coerce_int(os.environ.get("CLAUDE_PLUGIN_OPTION_DIRTY_TREE_THRESHOLD"), 1800)

    proc = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=str(state.project_root()),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        state.log_line("dirty-tree", "not a git repo — skipping")
        return 0

    status = subprocess.run(
        # `-uall` lists untracked FILES individually. Without it git collapses a wholly-untracked
        # directory to a single `?? design/` line, so the per-file proposal exclusion below never
        # sees a TRDD name — and that collapsed form is exactly the live case, because a project
        # whose first janitor proposal just landed has no tracked `design/` yet. It also makes the
        # "N uncommitted change(s)" count mean what it says. Ignored files are still skipped, so
        # this does not walk node_modules.
        ["git", "status", "--porcelain", "-uall"],
        cwd=str(state.project_root()),
        capture_output=True,
        text=True,
        check=False,
    )
    dirty_lines = sum(1 for line in status.stdout.splitlines() if line and not _is_janitor_proposal(line))

    if dirty_lines == 0:
        # Clean tree — clear state and rearm so the next dirty window
        # produces a fresh nudge instead of immediately re-emitting an
        # already-seen bucket key.
        try:
            dirty_since.unlink()
        except FileNotFoundError:
            pass
        if seen.exists():
            seen.write_text("")
        return 0

    now = int(time.time())
    if not dirty_since.exists():
        state.atomic_write(dirty_since, str(now))
        since = now
    else:
        since = state.read_int_state(dirty_since, now)
    age = now - since

    if age < threshold:
        return 0

    # Re-emit once per threshold-sized window so a long-ignored dirty tree
    # keeps nudging. Floor at 60s to guard against THRESHOLD=0 misconfig
    # (which would divide-by-zero on the bucket calc).
    window = max(threshold, 60)
    bucket = age // window
    age_m = age // 60

    line = dedupe.emit_once(
        seen,
        f"dirty@b{bucket}",
        f"[dirty-tree] Working tree has been dirty for ~{age_m}min ({dirty_lines} uncommitted change(s)). "
        f"Commit now — frequent commits are the recovery net. Stage specific files by name (never 'git add -A'). "
        f"If git safety blocks a destructive op: move files to a _dev/ folder, use 'git rm' to stage a recoverable "
        f"deletion, 'git stash' to park work, or create a backup branch.",
    )
    if line is not None:
        print(line)

    state.rotate_log_if_big("dirty-tree")
    return 0


if __name__ == "__main__":
    # `--one-shot` is the historical flag from the bash port. We accept it
    # as a no-op for backward compatibility — every Python detector is
    # one-shot by construction (no daemon mode).
    sys.exit(main())
