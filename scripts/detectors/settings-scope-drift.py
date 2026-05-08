#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Settings-scope drift — Python port of settings-scope-drift.sh.

Audits the tracking status of the project's Claude Code settings files
against the documented scope policy:

  * `.claude/settings.json`        SHOULD be git-tracked. Project-scope
                                   (permissions, hooks, MCP allowlists,
                                   etc.) — every collaborator needs them.
  * `.claude/settings.local.json`  SHOULD be gitignored. Personal local
                                   overrides (autoMode opt-ins, personal
                                   hooks, MCP allow/deny choices). If
                                   tracked, it leaks personal config —
                                   and worse, can include `enabledPlugins`
                                   overrides that teammates don't want
                                   to inherit.

Three drift classes per file:
  * wrong-direction-tracked    — settings.local.json IS tracked   → fix
  * wrong-direction-gitignored — settings.json IS gitignored      → fix
  * ambiguous (neither/nor)    — file exists but git status unset → decide
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


def main() -> int:
    state.init_state()

    seen = state.state_dir() / "settings-scope-drift-seen.txt"

    # `.claude/settings.json` — should be tracked.
    proj_status = git_utils.scope_tracking_status(".claude/settings.json")
    if proj_status == git_utils.GITIGNORED:
        _emit(
            seen,
            "settings-tracked-but-ignored@.claude/settings.json",
            "[settings-scope-drift] .claude/settings.json is gitignored — its purpose is project-scope "
            "(team-shared) settings. Teammates' checkouts won't see your hooks, permissions, or MCP "
            "allowlists. Either rename to .claude/settings.local.json, OR remove the matching .gitignore "
            "rule and 'git add .claude/settings.json'.",
        )
    elif proj_status == git_utils.AMBIGUOUS:
        _emit(
            seen,
            "ambig@.claude/settings.json",
            "[settings-scope-drift] .claude/settings.json is neither git-tracked nor gitignored — its "
            "scope is ambiguous. For team-shared settings: 'git add .claude/settings.json'. For personal: "
            "rename to .claude/settings.local.json AND ignore that name in .gitignore.",
        )

    # `.claude/settings.local.json` — should be gitignored.
    local_status = git_utils.scope_tracking_status(".claude/settings.local.json")
    if local_status == git_utils.TRACKED:
        _emit(
            seen,
            "local-leaked@.claude/settings.local.json",
            "[settings-scope-drift] .claude/settings.local.json is git-tracked — its purpose is personal "
            "local-scope overrides (autoMode flags, personal hooks, enabledPlugins overrides). Tracking it "
            "leaks your config to the team. Run: git rm --cached .claude/settings.local.json && "
            "grep -qxF '/.claude/settings.local.json' .gitignore || echo '/.claude/settings.local.json' >> .gitignore",
        )
    elif local_status == git_utils.AMBIGUOUS:
        _emit(
            seen,
            "ambig@.claude/settings.local.json",
            "[settings-scope-drift] .claude/settings.local.json exists but is neither tracked nor gitignored. "
            "It SHOULD be gitignored (it's personal config). Run: echo '/.claude/settings.local.json' >> .gitignore",
        )

    state.rotate_log_if_big("settings-scope-drift")
    return 0


if __name__ == "__main__":
    sys.exit(main())
