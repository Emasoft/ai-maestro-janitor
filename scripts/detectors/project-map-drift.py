#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""project-map-drift — nudge when the fenced CLAUDE.md project map is stale.

The maintainer half of the auto project map (TRDD-e247a349 §3). This detector
deliberately does the CHEAP DETECTION ONLY — it NEVER writes CLAUDE.md:

  - CLAUDE.md sits in the cached prompt prefix; rewriting it mid-session busts
    the context cache for the WHOLE context and every forked subagent
    (TRDD-e247a349 §5 — a careless write can burn a 5h token budget).
  - CLAUDE.md is co-owned by the human and the session's Claude. A background
    writer racing their edits is exactly the corruption class the user fears.
    The WRITE therefore stays human/agent-initiated (`repomap_generate.py`,
    which carries the lock + lost-update guard + byte-preservation invariant)
    at a cache-cheap moment (fresh session / post-compaction / pre-commit).

Per heartbeat (when due): opt-in flag present AND a map block exists →
compare the fence's `digest=` to the current repo digest (git HEAD +
porcelain hash — ZERO extraction cost). Unchanged → silent. Changed → ONE
deduped nudge naming the refresh command. No flag, no CLAUDE.md, no block,
malformed fences → silent no-op (the on-command owns insertion; malformed
fences are surfaced by the generator itself when run).

Opt-in: `$PROJECT/.janitor/state/repomap-opt-in.flag` — project-scoped
(this is a per-project map, NOT a machine-global daemon op), written by
`/janitor-auto-repomap-on`, removed by `/janitor-auto-repomap-off`.
"""

from __future__ import annotations

import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(_LIB))

import dedupe  # type: ignore[import-not-found]  # noqa: E402
import state  # type: ignore[import-not-found]  # noqa: E402
from repomap.markers import read_fence_header  # noqa: E402

# Reuse the generator's digest so detector and generator can never disagree
# about freshness semantics (scripts/ is not a package → runtime sys.path).
sys.path.insert(0, str(_LIB.parent))
from repomap_generate import repo_digest  # type: ignore[import-not-found]  # noqa: E402


def main() -> int:
    state.init_state()
    root = state.project_root()

    if not (Path(state.state_dir()) / "repomap-opt-in.flag").is_file():
        return 0  # feature OFF (default) — total no-op

    claude_md = root / "CLAUDE.md"
    if not claude_md.is_file():
        return 0
    try:
        header = read_fence_header(claude_md.read_text(encoding="utf-8"))
    except Exception:
        return 0  # malformed/unreadable → the generator reports it when run
    if header is None:
        return 0  # no block yet — insertion is the on-command's job

    current = repo_digest(root)
    recorded = header.get("digest", "")
    if current == recorded:
        return 0  # fresh — silent

    seen = Path(state.state_dir()) / "project-map-drift.seen"
    line = dedupe.emit_once(
        seen,
        f"stale@{current}",
        "[project-map-drift] The CLAUDE.md project map is STALE (repo changed since "
        f"digest {recorded}). Refresh at a cache-cheap moment (fresh session, post-"
        "compaction, or pre-commit) with: uv run scripts/repomap_generate.py "
        "— the janitor never rewrites CLAUDE.md itself (cache + co-ownership safety).",
    )
    if line is not None:
        print(line)

    state.rotate_log_if_big("project-map-drift")
    return 0


if __name__ == "__main__":
    sys.exit(main())
