# Cheap, zero-LLM filesystem prechecks for the memory-maintenance SCHEDULER
# (TRDD-3XS3PDCF).
#
# The scheduler (scripts/detectors/memory-maintenance.py) decides WHEN an editorial
# chore is due purely by CADENCE (memory_settings.is_due — a stat + int-compare on a
# stamp). Cadence-due is necessary but not sufficient: a chore can be due yet have
# NOTHING to do (e.g. SPLIT is due but no page exceeds the size cap). Emitting the
# marker anyway spawns a ~240k-token background opus agent that immediately abstains
# ("NOTHING DUE") — pure waste. With split_per_day=4.5 and a corpus where no page is
# ever over the cap, that is ~1M tokens/day of no-op spawns on the unattended-
# immortal use-case (the very drain that worsened a near-freeze).
#
# This module adds a SECOND emit condition for the chores whose idleness can be
# proven CHEAPLY and UNAMBIGUOUSLY from the filesystem alone: the scheduler emits the
# marker only when is_due AND content_has_work. It is an ADDITIONAL gate, NOT a
# second cadence gate — mark_ran stays the sole cadence authority (no VJ8L465M-class
# double-gate, TRDD-VJ8L465M), and the agent still trusts the marker (no agent
# change).
#
# FAIL-OPEN is the load-bearing safety rule: a precheck that WRONGLY says "no work"
# silently breaks a chore — strictly worse than the no-op it prevents. So a chore is
# suppressed ONLY when its idleness is cheaply PROVEN; every chore without an exact
# cheap precheck (and any precheck that can't determine its inputs) returns True =
# unchanged cadence-only behavior. Today SPLIT has a precheck (the size gate) and
# CONSOLIDATE has a STRUCTURAL-only precheck (TRDD-8UD3Q7K5, issue #64 — see below);
# HARVEST/REPAIR/ATOMIZE are documented follow-ups (their predicates need each
# skill's exact shape-check), and CONFLICT is genuinely SEMANTIC (contradictory-fact
# discovery) and stays agent-discovered.
#
# CONSOLIDATE's precheck is STRUCTURAL-ONLY, not a full content gate. A merge is
# governed by `memory_edit_verify.is_legal_merge`, whose THREE refusal grounds are
# structural (cross-tier / tier not in {aspect, component} / cross-type) and read
# from frontmatter alone, plus a FOURTH that is SEMANTIC (same subject? a 3rd
# same-subject page?) and only the agent can decide. The precheck checks ONLY the
# structural NECESSARY condition — "does the corpus hold >=2 pages sharing the same
# (tier, type) with a mergeable tier?". No pair => is_legal_merge would categorically
# refuse EVERY pair => the agent can only abstain => suppress (PROVEN idle). A pair
# present => still dispatch (fail-open on subject); the agent applies the semantic
# gate. This kills the issue #64 drain: a corpus of categorically-unmergeable
# singletons (e.g. a feedback x reference pair, or keyword-only over-clustering of
# distinct subjects) no longer re-spawns a ~226k-token opus agent every consolidate
# cadence (~2.5x/day) just to re-abstain.

from __future__ import annotations

from collections import Counter
from pathlib import Path

import memory_edit_verify  # sibling in scripts/lib/ — the SSOT for merge legality
import memory_scopes  # sibling in scripts/lib/ (the caller puts lib on sys.path)


def _candidate_pages(root: Path) -> list[Path]:
    """Every real committed NOTE under `root` — the exact candidate set the
    janitor-memory-split skill scans, via the shared SSOT.

    `memory_scopes.iter_note_files` excludes the transaction staging dir AND the
    PRIVATE user-mem store AND the generated/index files — matching the split
    skill's own `find` (which excludes `.maint-staging/`, `user-mem/`, and the
    generated basenames). Before the SSOT this used a raw `*.md` scan that
    excluded only `.maint-staging`, so it could count a private user-mem note or a
    detector-proposal report as an over-cap "page" (TRDD-87935f21 mandate #3)."""
    return memory_scopes.iter_note_files(root)


def split_has_work(root: Path, *, max_bytes: int) -> bool:
    """True iff some committed page in `root` is strictly larger than `max_bytes`
    (the split cap). Mirrors the split skill's `find -size +<cap>c` size gate with
    the SAME cap source (memory_settings split_max_bytes).

    This is the SIZE gate ONLY. The skill additionally refuses a tier:component or a
    <2-section page (one element = one page / un-splittable leaf), so a rare
    over-cap-but-unsplittable page still reaches the agent and abstains. The size
    gate eliminates the COMMON no-op — no page over the cap at all — which is the
    observed recurring drain; refining to 'over-cap AND splittable' is a follow-up.
    The caller guarantees max_bytes > 0 (see content_has_work fail-open)."""
    for p in _candidate_pages(root):
        try:
            if p.stat().st_size > max_bytes:
                return True
        except OSError:
            # An unreadable page is not provably idle — keep scanning. If nothing
            # else is over-cap we (correctly) report no work for the readable set.
            continue
    return False


def consolidate_has_work(root: Path) -> bool:
    """True iff some pair of candidate pages in `root` COULD be a legal merge —
    the cheap, zero-LLM STRUCTURAL necessary condition of `is_legal_merge`
    (TRDD-8UD3Q7K5, issue #64).

    `is_legal_merge` refuses a merge unless both pages share the SAME `metadata.tier`
    AND that tier is in `_MERGEABLE_TIERS` (= {aspect, component} — a `hub` is an
    overview, not a leaf) AND both share the SAME `metadata.type`. So a structural
    merge pair exists iff >=2 candidate pages share the same (tier, type) key with a
    mergeable tier. If NO such pair exists, `is_legal_merge` would categorically
    refuse EVERY pair, the agent can only abstain, and the dispatch is provably idle
    → suppress. If a pair DOES exist, return True (fail-open) and let the agent apply
    the SEMANTIC gate (same subject? a 3rd same-subject page?) — we never suppress a
    possibly-real merge.

    Cost: one rglob over the shared candidate SSOT + a tiny leading-frontmatter parse
    per page (no body read, no YAML engine, no LLM, no agent). Uses the SAME SSOTs the
    EXECUTOR uses — `memory_scopes.iter_note_files` (excludes `.maint-staging/`,
    `user-mem/`, generated/index basenames, `-proposed.md` reports) and
    `memory_edit_verify.parse_frontmatter` / `_MERGEABLE_TIERS` — so the precheck and
    the commit-time `is_legal_merge` can never drift (cf. TRDD-87935f21: one source of
    truth for merge legality)."""
    by_key: Counter[tuple[object, object]] = Counter()
    for p in _candidate_pages(root):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            # An unreadable page is not provably part of a mergeable pair — skip it.
            # If nothing else pairs, we (correctly) report no work for the rest.
            continue
        fm = memory_edit_verify.parse_frontmatter(text)
        tier = fm.get("tier")
        if tier not in memory_edit_verify._MERGEABLE_TIERS:
            continue  # hub / tier-less raw note → never a legal-merge leaf
        by_key[(tier, fm.get("type"))] += 1
        if by_key[(tier, fm.get("type"))] >= 2:
            return True  # found a structural pair — short-circuit (fail-open)
    return False


def content_has_work(intervention: str, root: Path, *, split_max_bytes: int) -> bool:
    """True iff `intervention` has actual work on the `root` corpus.

    FAIL-OPEN: returns True for every chore WITHOUT a cheap, exact precheck, and for
    SPLIT when the cap is non-positive (can't determine → never suppress). A chore is
    suppressed ONLY when its idleness is cheaply PROVEN; otherwise the scheduler
    keeps its existing cadence-only behavior."""
    if intervention == "split":
        if split_max_bytes <= 0:
            return True  # cap unreadable/disabled → fail-open (do not suppress)
        return split_has_work(root, max_bytes=split_max_bytes)
    if intervention == "consolidate":
        # STRUCTURAL-only gate (subject-sameness stays agent-discovered, fail-open).
        return consolidate_has_work(root)
    # harvest/repair/atomize: precheck is a documented follow-up (need each skill's
    # exact shape predicate). conflict: semantic, agent-discovered.
    return True
