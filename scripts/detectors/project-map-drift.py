#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""project-map-drift — nudge when the fenced CLAUDE.md project map is stale.

The maintainer half of the auto project map (TRDD-e247a349 §3). This detector
deliberately does the CHEAP DETECTION ONLY — it NEVER writes CLAUDE.md:

  - CLAUDE.md is co-owned by the human and the session's Claude. A background
    writer racing their edits is exactly the corruption class the user fears.
    The WRITE therefore stays human/agent-initiated (`repomap_generate.py`,
    which carries the lock + lost-update guard + byte-preservation invariant).

    THIS reason is the whole reason, and it is unaffected by the correction
    below — do not read that correction as licence for the heartbeat to write
    CLAUDE.md. Two independent grounds used to be given; one of them was
    false, and the surviving one still forbids the write on its own.

  - CORRECTED 2026-08-26 (TRDD-LFSWY0C6): this file used to give a SECOND
    ground — that rewriting CLAUDE.md mid-session busts the context cache for
    the whole window and every forked subagent, "a careless write can burn a
    5h token budget". MEASURED FALSE, over the recorded per-turn `usage` in
    this project's own session transcripts: of 307 turns immediately following
    a CLAUDE.md Edit/Write, the worst `cache_creation_input_tokens` was 65,923
    and the median 1,525 — against 598,351 max / 1,104 median across the other
    108,303 turns. Full-prefix rewrites are real and DO occur here (11.4x
    write/read at the extreme); they simply never follow a CLAUDE.md edit.

    Recording it rather than deleting it, because the false claim had a COST:
    it told every agent that read it to defer the refresh, so the index sat
    stale for days and the deferral was then misread as "advisories get
    ignored" — a second wrong diagnosis built on the first.

TWO INDEPENDENT HALVES, and keeping them independent is load-bearing:

  * THE SLIM / WIKIMEM-INDEX HALF runs on every fire, with NO opt-in. It governs the
    `JANITOR-WIKIMEM-INDEX-*` fence and the narrative-byte budget — a different fence and a
    different feature from the map. Silent when the project has no PROJECT wikimem corpus.
  * THE MAP HALF needs the opt-in flag AND an existing `JANITOR-REPO-MAP-*` block →
    compare the fence's `digest=` to the current repo digest (git HEAD + porcelain hash —
    ZERO extraction cost). Unchanged → silent. Changed → ONE deduped nudge naming the
    refresh command. No flag, no CLAUDE.md, no block, malformed fences → silent no-op (the
    on-command owns insertion; malformed fences are surfaced by the generator when run).

The slim half used to sit BEHIND both map gates, which is a defect with a measured cost
(TRDD-LFSWY0C6): a project that keeps the index but deletes the map — this repo, deliberately,
because the map cost ~46k tokens per turn — got no index check at all, and its index sat stale
for FIVE DAYS. Do not re-couple them.

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
    """The slim-CLAUDE.md half (TRDD-H12K9JYX): when a CLAUDE.md violates the slim contract
    or its wikimem index went stale, emit ONE deduped nudge. NUDGE-ONLY for the same two
    reasons the map half never writes: the prompt-cache bust and the co-ownership race. The
    dedupe key carries the corpus digest + a violation fingerprint so a FIXED contract stays
    silent and a NEW violation re-fires.

    The GATE is the PROJECT wikimem corpus, not the map fence. This docstring used to say
    "a janitor-managed CLAUDE.md (it carries the map fence — that is what opted it in)",
    which described a coupling that was itself the bug (TRDD-LFSWY0C6): the index and the map
    are separate features, and a project can keep one without the other. Presence of a corpus
    is what makes an index check meaningful; presence of a map says nothing about it."""
    try:
        pages = cslim.scan_pages(root / ".claude" / "project" / "memory")
        if not pages:
            # No PROJECT wikimem corpus → nothing to index, and the slim migration
            # presupposes the memory system is bootstrapped (/janitor-memory-bootstrap).
            # Nudging here would point at a command that can only refuse.
            return
        # `require_map` only when this project actually opted in to the auto map. The flag
        # is the real opt-in signal; the fence's presence is merely its consequence, so
        # keying on the fence would report every opted-OUT project as broken forever.
        opted_in = (root / ".janitor" / "state" / "repomap-opt-in.flag").is_file()
        problems = cslim.slim_violations(text, require_map=opted_in)
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
        "narrative into wikimem pages via /janitor-project-cld-md-optimizer. Safe to run NOW "
        "— a CLAUDE.md edit does not bust the context cache (measured, TRDD-LFSWY0C6); the "
        "janitor never rewrites CLAUDE.md itself because it is co-owned with you.",
    )
    if line is not None:
        print(line)


def main() -> int:
    state.init_state()
    root = state.project_root()

    claude_md = root / "CLAUDE.md"
    if not claude_md.is_file():
        return 0
    try:
        text = claude_md.read_text(encoding="utf-8")
    except Exception:
        return 0  # malformed/unreadable → the generator reports it when run

    # THE SLIM/WIKIMEM-INDEX HALF RUNS UNCONDITIONALLY — it is NOT part of the map feature,
    # and gating it behind one was a real defect with a measured cost (TRDD-LFSWY0C6).
    #
    # These are two different fences. `read_fence_header` reads the REPO-MAP fence
    # (`JANITOR-REPO-MAP-*`); the slim contract and the staleness check below are about the
    # WIKIMEM INDEX fence (`JANITOR-WIKIMEM-INDEX-*`) and the narrative-byte budget. A project
    # can want the index and not the map — THIS repo is exactly that case: it deleted its map
    # deliberately (it cost ~46k tokens on every turn of every session) while keeping the index.
    #
    # Under the old order that project got NEITHER, via two independent gates it had no reason
    # to connect: the `repomap-opt-in.flag` early-return, and `header is None` for the map fence
    # it does not have. Measured consequence: the wikimem index sat STALE for FIVE DAYS across
    # many sessions. TRDD-LFSWY0C6 read that as "the advisory fires and nobody acts on it" and
    # built its whole argument on it — but the advisory was never reachable. The nudge did not
    # go unheeded; it did not exist.
    _slim_contract_nudge(root, text)

    if not (Path(state.state_dir()) / "repomap-opt-in.flag").is_file():
        return 0  # the MAP feature is OFF (default) — the slim half above already ran
    try:
        header = read_fence_header(text)
    except Exception:
        return 0
    if header is None:
        return 0  # no map block yet — insertion is the on-command's job

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
        f"digest {recorded}). Safe to refresh NOW with: uv run scripts/repomap_generate.py "
        "— a CLAUDE.md edit does not bust the context cache (measured, TRDD-LFSWY0C6). The "
        "janitor never rewrites CLAUDE.md itself because it is co-owned with you.",
    )
    if line is not None:
        print(line)

    state.rotate_log_if_big("project-map-drift")
    return 0


if __name__ == "__main__":
    sys.exit(main())
