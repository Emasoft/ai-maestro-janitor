#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""project-memory-tracked — keep PROJECT-scope memory git-TRACKED (TRDD-3f7b6807).

The PROJECT memory scope (`<repo>/.claude/project/memory/`) is shared with every
contributor and MUST live in the repo. The only sanctioned mechanism is a
`.gitignore` NEGATION (exception) line — NEVER `git add`, NEVER `git add -f`,
NEVER force-staging (those bypass the user's ignore intent and can drag in
sibling files they deliberately excluded).

This heartbeat detector calls `project_memory_tracked.ensure_tracked`, which:
  * is a no-op when the memory dir is absent or already un-ignored;
  * else APPENDS the canonical exception triplet (idempotent + atomic);
  * and flags `needs-manual` when a directory-pruning ignore (bare `.claude/`)
    blocks git from descending so an exception can't apply — without ever
    rewriting the existing ignore line.

It surfaces ONE drift line ONLY when ensure_tracked actually changed something
("exception-added") or a human must act ("needs-manual"); the result is deduped
via a per-detector seen-file so the same outcome never repeats. It is silent for
"absent" / "already-tracked" / "error" (an indeterminate probe is not actionable
and must not nag). Always exits 0. Project-scoped — never touches user/global
scope.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import project_memory_tracked  # noqa: E402
import state  # noqa: E402

_NAME = "project-memory-tracked"


def main() -> int:
    state.init_state()
    project_root = state.project_root()

    action, detail = project_memory_tracked.ensure_tracked(project_root)

    if action == "exception-added":
        safe = state.sanitize_for_drift_line(detail)
        # Key on the ACTION (not on the exact lines added) so once we've
        # reported that the exception was installed for this project, a later
        # idempotent run doesn't re-nag. emit_forget is unnecessary: once tracked
        # the scope stays tracked, and a regression (someone deletes the
        # exception) flips check-ignore back, producing a fresh "exception-added"
        # which this same key will surface again because we never wrote it then.
        seen = state.state_dir() / "project-memory-tracked-seen.txt"
        line = dedupe.emit_once(
            seen,
            "exception-added",
            "[project-memory-tracked] PROJECT memory `.claude/project/memory/` was "
            "git-IGNORED — added .gitignore exception line(s) so it is tracked + "
            f"shared with every contributor: {safe}. Review the .gitignore diff and "
            "commit it (NEVER `git add -f` — the exception is the right mechanism).",
        )
        if line is not None:
            print(line)

    elif action == "needs-manual":
        safe = state.sanitize_for_drift_line(detail)
        seen = state.state_dir() / "project-memory-tracked-seen.txt"
        line = dedupe.emit_once(
            seen,
            "needs-manual",
            "[project-memory-tracked] PROJECT memory `.claude/project/memory/` is "
            f"git-IGNORED and a .gitignore exception cannot fix it: {safe}. The "
            "memory scope must be tracked + shared; fix the ignore line by hand.",
        )
        if line is not None:
            print(line)

    # "absent" / "already-tracked" / "error" → silent (nothing actionable).
    state.rotate_log_if_big(_NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
