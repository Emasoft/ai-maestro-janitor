#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""project-map-drift — nudge when the generated PROJECT_MAP.md is missing or stale.

The maintainer half of the auto project map (TRDD-e247a349 §3, TRDD-FADYLSQB). The map
lives in the git-excluded root file PROJECT_MAP.md, never in CLAUDE.md. This detector
deliberately does the CHEAP DETECTION ONLY — it NEVER writes anything:

  - The WRITE stays human/agent-initiated (`repomap_generate.py`, which carries the lock,
    the verified write and — for a leftover legacy REPO-MAP fence — the one-time strip of a
    block from CLAUDE.md). CLAUDE.md is co-owned by the human and the session's Claude, so a
    background writer racing their edits is exactly the corruption class the user fears.
    THIS reason is the whole reason the heartbeat must not touch CLAUDE.md.

  - CORRECTED 2026-08-26 (TRDD-LFSWY0C6): this file used to give a SECOND ground — that
    rewriting CLAUDE.md mid-session busts the context cache for the whole window and every
    forked subagent, "a careless write can burn a 5h token budget". MEASURED FALSE, over the
    recorded per-turn `usage` in this project's own session transcripts: of 307 turns
    immediately following a CLAUDE.md Edit/Write, the worst `cache_creation_input_tokens`
    was 65,923 and the median 1,525 — against 598,351 max / 1,104 median across the other
    108,303 turns. Full-prefix rewrites are real and DO occur here (11.4x write/read at the
    extreme); they simply never follow a CLAUDE.md edit.

    Recording it rather than deleting it, because the false claim had a COST: it told every
    agent that read it to defer the refresh, so the index sat stale for days and the deferral
    was then misread as "advisories get ignored" — a second wrong diagnosis built on the first.

THREE INDEPENDENT PARTS, and keeping them independent is load-bearing:

  * THE SLIM / WIKIMEM-INDEX HALF runs on every fire, with NO opt-in. It governs the
    `JANITOR-WIKIMEM-INDEX-*` fence and the narrative-byte budget — a different feature from
    the map. Silent when the project has no PROJECT wikimem corpus.
  * THE LEGACY-FENCE NUDGE also runs on every fire, with NO opt-in: a leftover
    `JANITOR-REPO-MAP-*` block in CLAUDE.md is dead weight on every turn whether or not the
    project opted in, and `repomap_generate.py` strips it once.
  * THE MAP HALF needs the opt-in flag. Missing PROJECT_MAP.md, a stale one (the header's
    `digest=` compared with the current repo digest — git HEAD + porcelain hash, ZERO
    extraction cost — and confirmed by the shared `current_map_sha` probe), or a CLAUDE.md
    that names PROJECT_MAP each emit ONE deduped nudge. A PROJECT_MAP.md without a generated
    header is not ours: silent, the generator refuses to touch it.

The slim half used to sit BEHIND both map gates, which is a defect with a measured cost
(TRDD-LFSWY0C6): a project that keeps the index but deletes the map — this repo, deliberately,
because the map cost ~46k tokens per turn — got no index check at all, and its index sat stale
for FIVE DAYS. Do not re-couple them.

Opt-in: `$PROJECT/.janitor/state/repomap-opt-in.flag` — project-scoped
(this is a per-project map, NOT a machine-global daemon op), written by
`/janitor-auto-repomap-on`, removed by `/janitor-auto-repomap-off`.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_LIB = Path(__file__).resolve().parent.parent / "lib"
sys.path.insert(0, str(_LIB))

import dedupe  # type: ignore[import-not-found]  # noqa: E402
import state  # type: ignore[import-not-found]  # noqa: E402
from repomap import MalformedFences, has_map_block, read_header  # noqa: E402
from repomap import claudemd_slim as cslim  # noqa: E402

# Reuse the generator's digest and hash so detector and generator can never disagree
# about freshness semantics (scripts/ is not a package → runtime sys.path).
sys.path.insert(0, str(_LIB.parent))
from repomap_generate import MAP_NAME, current_map_sha, repo_digest  # type: ignore[import-not-found]  # noqa: E402

# The name as a whole token: `CLAUDE_PLUGIN_OPTION_PROJECT_MAP_DRIFT_INTERVAL` is not a mention.
_NAMES_MAP_RE = re.compile(r"(?<![A-Za-z0-9_])PROJECT_MAP(?![A-Za-z0-9_])")


def _seen_file() -> Path:
    return Path(state.state_dir()) / "project-map-drift.seen"


def _emit(key: str, message: str) -> None:
    """Print `message` once per `key` (the shared dedupe file)."""
    line = dedupe.emit_once(_seen_file(), key, message)
    if line is not None:
        print(line)


def _slim_contract_nudge(root: Path, text: str) -> None:
    """The slim-CLAUDE.md half (TRDD-H12K9JYX): when a CLAUDE.md violates the slim contract
    or its wikimem index went stale, emit ONE deduped nudge. NUDGE-ONLY because CLAUDE.md is
    co-owned with the human (the co-ownership race). The dedupe key carries the corpus digest
    + a violation fingerprint so a FIXED contract stays silent and a NEW violation re-fires.

    The GATE is the PROJECT wikimem corpus, not the map. This docstring used to say
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
        problems = cslim.slim_violations(text)
        if cslim.index_is_stale(text, pages):
            problems.append("wikimem index stale")
    except Exception:
        return  # malformed fences etc. — the CLI reports precisely when run
    if not problems:
        return
    digest = cslim.corpus_digest(pages)
    _emit(
        f"slim@{digest}@{len(problems)}:{problems[0][:40]}",
        "[project-map-drift] CLAUDE.md breaks the slim contract: "
        + "; ".join(p.split(" (")[0] for p in problems[:3])
        + ". Refresh the index with `uv run scripts/claudemd_slim.py index` or migrate "
        "narrative into wikimem pages via /janitor-project-cld-md-optimizer. Safe to run NOW "
        "— a CLAUDE.md edit does not bust the context cache (measured, TRDD-LFSWY0C6); the "
        "janitor never rewrites CLAUDE.md itself because it is co-owned with you.",
    )


def _nudge_while(key: str, active: bool, message: str) -> None:
    """One nudge per EPISODE of a condition, not once ever: `emit_once` latches its key
    forever, so a fence/mention/missing-map that came back after being fixed would stay
    silent. Forgetting the key while the condition is clear re-arms it."""
    if active:
        _emit(key, message)
    else:
        dedupe.emit_forget(_seen_file(), key)


def _legacy_fence_nudge(text: str) -> None:
    """A leftover `JANITOR-REPO-MAP-*` block in CLAUDE.md. NOT behind the opt-in flag: the
    block is dead weight on every turn of an opted-out project too, and the strip is the
    generator's one-time job. The nudge says the generator also writes PROJECT_MAP.md (it
    has no opt-in check: the strip only happens after a verified map write). A malformed
    fence pair stays silent here — the generator surfaces that precisely when run."""
    try:
        present = has_map_block(text)
    except MalformedFences:
        return
    _nudge_while(
        "legacy-fence",
        present,
        "[project-map-drift] CLAUDE.md still carries a legacy REPO-MAP block. Run "
        "`uv run scripts/repomap_generate.py`; it strips the fence once, and as a side effect "
        "writes the git-excluded PROJECT_MAP.md (the map now lives there).",
    )


def _map_nudges(root: Path, claude_md_text: str | None) -> None:
    """The opt-in map half. Nudges only; never writes."""
    _nudge_while(
        "claude-md-names-map",
        claude_md_text is not None and _NAMES_MAP_RE.search(claude_md_text) is not None,
        "[project-map-drift] CLAUDE.md names PROJECT_MAP. CLAUDE.md has no map element "
        "(PRRD G7.3), so remove the mention.",
    )
    target = root / MAP_NAME
    _nudge_while(
        "map-missing",
        not target.is_file(),
        "[project-map-drift] PROJECT_MAP.md is missing (auto map is on). Generate it with: "
        "uv run scripts/repomap_generate.py",
    )
    if not target.is_file():
        return
    header = read_header(target.read_text(encoding="utf-8", errors="replace"))
    if header is None:
        return  # not a map this tooling wrote — the generator refuses to touch it, so do we
    current = repo_digest(root)
    recorded = header["digest"]
    if current == recorded:
        return  # fresh — silent (no commit/edit since the last generation)

    # The digest moves on EVERY commit/edit and can never catch up (the generator skips the
    # write when the structure hash matches), so a digest mismatch alone would re-fire a
    # false STALE nudge forever on structure-preserving changes (review wf_6aee2965). Confirm
    # with the AUTHORITATIVE structure probe — the same extract+hash `--check` uses, via
    # `current_map_sha`, which hashes WITH the coverage note exactly as the writer does
    # (TRDD-6HFOB5S4: omitting it nudged STALE forever on any repo that has a note) — and
    # cache the verdict per digest so the extraction runs once per commit, not per heartbeat.
    fresh_stamp = Path(state.state_dir()) / "project-map-fresh-at.digest"
    try:
        if fresh_stamp.read_text(encoding="utf-8").strip() == current:
            return  # this exact digest already verified structure-fresh
    except OSError:
        pass
    if header["sha"] == current_map_sha(root, header):
        state.atomic_write(fresh_stamp, current)
        return  # structure unchanged — the map is NOT stale; stay silent
    _emit(
        f"stale@{current}",
        f"[project-map-drift] PROJECT_MAP.md is STALE (repo changed since digest {recorded}). "
        "Refresh it with: uv run scripts/repomap_generate.py",
    )


def main() -> int:
    state.init_state()
    root = state.project_root()

    claude_md = root / "CLAUDE.md"
    text: str | None = None
    if claude_md.is_file():
        try:
            text = claude_md.read_text(encoding="utf-8")
        except Exception:
            text = None  # unreadable → the generator reports it when run

    # THE SLIM/WIKIMEM-INDEX HALF RUNS UNCONDITIONALLY — it is NOT part of the map feature,
    # and gating it behind one was a real defect with a measured cost (TRDD-LFSWY0C6).
    #
    # A project can want the wikimem index and not the map — THIS repo is exactly that case:
    # it deleted its map deliberately (it cost ~46k tokens on every turn of every session)
    # while keeping the index. Under the old order that project got NO index check, via two
    # independent gates it had no reason to connect: the `repomap-opt-in.flag` early-return,
    # and `header is None` for a map fence it does not have. Measured consequence: the wikimem
    # index sat STALE for FIVE DAYS across many sessions. TRDD-LFSWY0C6 read that as "the
    # advisory fires and nobody acts on it" and built its whole argument on it — but the
    # advisory was never reachable. The nudge did not go unheeded; it did not exist.
    if text is not None:
        _slim_contract_nudge(root, text)
        _legacy_fence_nudge(text)

    if not (Path(state.state_dir()) / "repomap-opt-in.flag").is_file():
        return 0  # the MAP feature is OFF (default) — the halves above already ran
    _map_nudges(root, text)

    state.rotate_log_if_big("project-map-drift")
    return 0


if __name__ == "__main__":
    sys.exit(main())
