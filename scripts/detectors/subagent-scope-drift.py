#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.10"
# ///
"""Subagent-scope drift — Python port of subagent-scope-drift.sh.

Flags `.claude/agents/*.md` files whose tracking status is ambiguous.
Per the docs (settings#what-uses-scopes), subagents have NO formal local
scope — Claude Code reads agents from `~/.claude/agents/` (user) and
`<root>/.claude/agents/` (project). There is no
`<root>/.claude/agents.local/` or similar.

Functionally, the user can keep an agent personal by gitignoring it
under `.claude/agents/`; it still loads at session start, but it never
reaches a teammate's checkout.

So the only legitimate states for a project-level agent file are:
  * git-tracked  → 'project scope' — shared with the team
  * gitignored   → 'informally local' — personal to this checkout

Anything else (file on disk, neither tracked nor ignored) is the
tracking-ambiguity bug: agents disappear from teammates' checkouts
without warning, OR personal agents get committed accidentally.

The detector batches: rather than emit one drift line per ambiguous
file, we collect ALL ambiguous files and emit a single summary line
listing the first 5 + a count. Each summary is dedup'd by the
concatenation of file names so re-running is silent until the set
changes.
"""

from __future__ import annotations

import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import git_utils  # noqa: E402
import state  # noqa: E402


def main() -> int:
    state.init_state()

    seen = state.state_dir() / "subagent-scope-drift-seen.txt"
    root = state.project_root()
    agents_dir = root / ".claude" / "agents"
    if not agents_dir.is_dir():
        return 0

    ambiguous: list[str] = []
    for agent_path in sorted(agents_dir.rglob("*.md")):
        if not agent_path.is_file():
            continue
        rel = str(agent_path.relative_to(root))
        if git_utils.scope_tracking_status(rel) == git_utils.AMBIGUOUS:
            ambiguous.append(rel)

    if not ambiguous:
        return 0

    # Build summary: first 5 lines indented, plus a count line if more.
    sample_lines = [f"  - {p}" for p in ambiguous[:5]]
    if len(ambiguous) > 5:
        sample_lines.append(f"  - …and {len(ambiguous) - 5} more")
    sample = "\n".join(sample_lines)

    # Dedup key is a hash of the full sorted file list — re-emits only
    # when the SET of ambiguous files changes (a single new agent
    # appearing or disappearing rotates the key).
    fp = zlib.crc32("\n".join(sorted(ambiguous)).encode("utf-8")) & 0xFFFFFFFF

    line = dedupe.emit_once(
        seen,
        f"ambig-set@{fp}",
        f"[subagent-scope-drift] {len(ambiguous)} agent file(s) under .claude/agents/ are neither "
        f"git-tracked nor gitignored. Each must be either: 'git add' (project scope, shared with team) "
        f"OR added to .gitignore (informally local, personal to this checkout). Subagents have no "
        f"formal local scope — the git status IS the scope signal. Affected:\n{sample}",
    )
    if line is not None:
        print(line)

    state.rotate_log_if_big("subagent-scope-drift")
    return 0


if __name__ == "__main__":
    sys.exit(main())
