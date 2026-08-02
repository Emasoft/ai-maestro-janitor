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
from repomap import claudemd_slim as cslim  # noqa: E402
from repomap.markers import read_fence_header  # noqa: E402

# Reuse the generator's digest so detector and generator can never disagree
# about freshness semantics (scripts/ is not a package → runtime sys.path).
sys.path.insert(0, str(_LIB.parent))
from repomap.renderer import structure_hash  # noqa: E402
from repomap_generate import extract_all, load_excludes, repo_digest  # type: ignore[import-not-found]  # noqa: E402


def _slim_contract_nudge(root: Path, text: str) -> None:
    """The slim-CLAUDE.md half (TRDD-H12K9JYX): when a janitor-managed CLAUDE.md (it
    carries the map fence — that is what opted it in) violates the slim contract or its
    wikimem index went stale, emit ONE deduped nudge. NUDGE-ONLY for the same two reasons
    the map half never writes: the prompt-cache bust and the co-ownership race. The
    dedupe key carries the corpus digest + a violation fingerprint so a FIXED contract
    stays silent and a NEW violation re-fires."""
    try:
        pages = cslim.scan_pages(root / ".claude" / "project" / "memory")
        if not pages:
            # No PROJECT wikimem corpus → nothing to index, and the slim migration
            # presupposes the memory system is bootstrapped (/janitor-memory-bootstrap).
            # Nudging here would point at a command that can only refuse.
            return
        problems = cslim.slim_violations(text)
        if cslim.index_is_stale(text, pages):
            problems.append("wikimem index stale")
    except Exception:
        return  # malformed fences etc. — the CLI reports precisely when run
    if not problems:
        return
    digest = cslim.corpus_digest(pages)
    key = f"slim@{digest}@{len(problems)}:{problems[0][:40]}"
    seen = Path(state.state_dir()) / "project-map-drift.seen"
    line = dedupe.emit_once(
        seen,
        key,
        "[project-map-drift] CLAUDE.md breaks the slim contract: "
        + "; ".join(p.split(" (")[0] for p in problems[:3])
        + ". Refresh the index with `uv run scripts/claudemd_slim.py index` or migrate "
        "narrative into wikimem pages via /janitor-claude-md-slim — at a cache-cheap "
        "moment; the janitor never rewrites CLAUDE.md itself.",
    )
    if line is not None:
        print(line)


def main() -> int:
    state.init_state()
    root = state.project_root()

    if not (Path(state.state_dir()) / "repomap-opt-in.flag").is_file():
        return 0  # feature OFF (default) — total no-op

    claude_md = root / "CLAUDE.md"
    if not claude_md.is_file():
        return 0
    try:
        text = claude_md.read_text(encoding="utf-8")
        header = read_fence_header(text)
    except Exception:
        return 0  # malformed/unreadable → the generator reports it when run
    if header is None:
        return 0  # no block yet — insertion is the on-command's job

    # A map-managed CLAUDE.md is also slim-managed (owner directive 2026-08-02) — check
    # the cheap half first; it needs no extraction.
    _slim_contract_nudge(root, text)

    current = repo_digest(root)
    recorded = header.get("digest", "")
    if current == recorded:
        return 0  # fresh — silent (no commit/edit since the last generation)

    # The digest moves on EVERY commit/edit and can never catch up (the generator
    # skips the write when the structure hash matches), so a digest mismatch alone
    # would re-fire a false STALE nudge forever on structure-preserving changes
    # (review wf_6aee2965). Confirm with the AUTHORITATIVE structure probe — the
    # same extract+hash the generator uses — and cache the verdict per digest so
    # the extraction runs once per commit, not once per heartbeat.
    fresh_stamp = Path(state.state_dir()) / "project-map-fresh-at.digest"
    try:
        if fresh_stamp.read_text(encoding="utf-8").strip() == current:
            return 0  # this exact digest already verified structure-fresh
    except OSError:
        pass
    try:
        maps = extract_all(root, load_excludes(root))
    except Exception:
        maps = []
    if maps and header.get("sha") == structure_hash(maps):
        state.atomic_write(fresh_stamp, current)
        return 0  # structure unchanged — the map is NOT stale; stay silent

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
