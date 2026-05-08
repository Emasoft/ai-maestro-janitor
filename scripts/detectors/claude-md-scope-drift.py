#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.10"
# ///
"""CLAUDE.md scope drift — Python port of claude-md-scope-drift.sh.

Audits the project memory files for tracking-status correctness:

  * `CLAUDE.md`            (project root, primary location)
                           SHOULD be tracked. Project memory is
                           inherently shared with the team.
  * `.claude/CLAUDE.md`    (alternate project location, equally valid)
                           SHOULD be tracked, same reasoning.
  * `CLAUDE.local.md`      Personal memory overrides. SHOULD be
                           gitignored. Tracking it leaks personal
                           notes/preferences to the team.

Note that Claude Code reads BOTH `CLAUDE.md` and `.claude/CLAUDE.md` if
both exist — they're not mutually exclusive. We audit each independently.

Three drift classes per file:
  * wrong-direction-tracked    — CLAUDE.local.md IS tracked       → fix
  * wrong-direction-gitignored — CLAUDE.md is gitignored          → fix
  * ambiguous                  — file exists, git status unset    → decide
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import git_utils  # noqa: E402
import state  # noqa: E402


def _emit(seen: Path, key: str, msg: str) -> None:
    line = dedupe.emit_once(seen, key, msg)
    if line is not None:
        print(line)


def _audit_should_be_tracked(seen: Path, rel: str) -> None:
    status = git_utils.scope_tracking_status(rel)
    if status == git_utils.GITIGNORED:
        _emit(
            seen,
            f"tracked-but-ignored@{rel}",
            f"[claude-md-scope-drift] {rel} is gitignored — its purpose is project memory, shared with "
            f"the team. Teammates won't see it. Either remove the matching .gitignore rule and "
            f"'git add {rel}', OR rename to CLAUDE.local.md if you intended it to be personal.",
        )
    elif status == git_utils.AMBIGUOUS:
        _emit(
            seen,
            f"ambig@{rel}",
            f"[claude-md-scope-drift] {rel} is neither git-tracked nor gitignored. For team-shared "
            f"project memory: 'git add {rel}'. For personal context: rename to CLAUDE.local.md and add "
            f"'/CLAUDE.local.md' to .gitignore.",
        )


def _audit_should_be_gitignored(seen: Path, rel: str) -> None:
    status = git_utils.scope_tracking_status(rel)
    if status == git_utils.TRACKED:
        _emit(
            seen,
            f"local-leaked@{rel}",
            f"[claude-md-scope-drift] {rel} is git-tracked — its purpose is personal memory overrides, "
            f"not team-shared content. Tracking it leaks personal notes to the team. Run: "
            f"git rm --cached {rel} && grep -qxF '/{rel}' .gitignore || echo '/{rel}' >> .gitignore",
        )
    elif status == git_utils.AMBIGUOUS:
        _emit(
            seen,
            f"ambig@{rel}",
            f"[claude-md-scope-drift] {rel} exists but is neither tracked nor gitignored. It SHOULD be "
            f"gitignored (it's personal memory). Run: echo '/{rel}' >> .gitignore",
        )


def main() -> int:
    state.init_state()

    seen = state.state_dir() / "claude-md-scope-drift-seen.txt"

    _audit_should_be_tracked(seen, "CLAUDE.md")
    _audit_should_be_tracked(seen, ".claude/CLAUDE.md")
    _audit_should_be_gitignored(seen, "CLAUDE.local.md")

    state.rotate_log_if_big("claude-md-scope-drift")
    return 0


if __name__ == "__main__":
    sys.exit(main())
