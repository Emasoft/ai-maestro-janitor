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
# unchanged cadence-only behavior. Today SPLIT has a precheck (the size gate),
# CONSOLIDATE has a STRUCTURAL-only precheck (TRDD-8UD3Q7K5, issue #64 — see below),
# and REPAIR/ATOMIZE have STRUCTURAL prechecks (TRDD-3XS3PDCF follow-up — see each
# function for the exact predicate + its documented residual). HARVEST stays a
# follow-up — BLOCKED until the coexistence-harvest model stabilizes (TRDD-ab232dbd
# #231/#232): a predicate written against either in-flux model would wrong-suppress
# against the other. CONFLICT is genuinely SEMANTIC (contradictory-fact discovery)
# and stays agent-discovered.
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

import re
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
            # FAIL-OPEN (libs audit L-11): an unreadable page is NOT provably idle —
            # it could be the very page over the cap, so skipping it and reporting
            # "no work" for the readable rest would wrongly SUPPRESS the chore.
            # Dispatch instead; the agent can surface the I/O problem.
            return True
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
            # FAIL-OPEN (libs audit L-11): an unreadable page could be one half of a
            # mergeable pair, so skipping it could wrongly suppress the chore.
            return True
        fm = memory_edit_verify.parse_frontmatter(text)
        tier = fm.get("tier")
        if tier not in memory_edit_verify._MERGEABLE_TIERS:
            continue  # hub / tier-less raw note → never a legal-merge leaf
        by_key[(tier, fm.get("type"))] += 1
        if by_key[(tier, fm.get("type"))] >= 2:
            return True  # found a structural pair — short-circuit (fail-open)
    return False


# Raw-line regexes for the repair/atomize predicates. Top-level `ocd:`/`lmd:` must be
# checked on the RAW frontmatter lines because parse_frontmatter FLATTENS nested
# `metadata.ocd`/`metadata.lmd` into the same dict — key-presence alone cannot see
# the historical NESTED placement (issue #56) that repair normalizes.
_TOP_LEVEL_DATE_RES = tuple(re.compile(rf"^{k}\s*:", re.M) for k in ("ocd", "lmd"))
_FOOTNOTE_DEF_RE = re.compile(r"^\[\^[^\]]+\]\s*:")


def _split_page(text: str) -> tuple[str | None, str]:
    """(frontmatter_block, body) — block is None when the page has no well-formed
    leading ``---`` fence pair (same tolerance as memory_scopes.is_curated_wiki_page)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text
    for i, ln in enumerate(lines[1:], start=1):
        if ln.strip() == "---":
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1 :])
    return None, text  # unclosed fence → treat as no frontmatter (malformed)


def _page_needs_repair(text: str) -> bool:
    """True iff this page exhibits a STRUCTURALLY-detectable defect from the
    janitor-memory-repair checklist. Every check mirrors a bar `verify_repair`
    (or the skill's own diagnosis list) enforces, via the same SSOT constants —
    so the precheck and the commit-time verifier can never drift."""
    fm_block, _body = _split_page(text)
    if fm_block is None:
        return True  # no/unclosed frontmatter → invisible to ranked recall
    meta = memory_edit_verify.parse_frontmatter(text)
    for key in memory_edit_verify._REQUIRED_FM_KEYS:
        if not str(meta.get(key, "")).strip():
            return True  # missing/empty required key — verify_repair's own bar
    if str(meta.get("tier", "")).strip() not in memory_edit_verify._VALID_TIERS:
        return True  # tier outside the legal set → repair re-tags it
    if memory_edit_verify._LESSONS_HEADING not in text:
        return True  # the standing Notes section is mandatory on every page
    for pat in _TOP_LEVEL_DATE_RES:
        if not pat.search(fm_block):
            return True  # ocd/lmd present only NESTED → placement-normalization work
    tier = str(meta.get("tier", "")).strip()
    has_applies = "## Applies to" in text
    has_governed = "## Governed by" in text
    if tier in ("aspect", "hub") and has_governed and not has_applies:
        return True  # a radiator built as a receiver (inverted tier shape)
    if tier == "component" and has_applies:
        return True  # a receiver that radiates (the mirror inversion)
    return False


def repair_has_work(root: Path) -> bool:
    """True iff some candidate page in `root` is STRUCTURALLY malformed per the
    janitor-memory-repair checklist (TRDD-3XS3PDCF follow-up).

    STRUCTURAL-only, like consolidate's gate: it detects the machine-checkable
    subset of the repair checklist (missing/partial frontmatter — including RAW
    harness buffer notes, which the skill explicitly upgrades; invalid tier;
    nested ocd/lmd placement; missing Notes section; inverted tier shape).
    DOCUMENTED RESIDUAL: the two SEMANTIC-only defects (an answer-shaped
    `description`, a page's own one-sided [[link]]) are not cheaply detectable,
    so a corpus whose ONLY defects are semantic is suppressed until the librarian
    surfaces them or any structural defect appears — the same
    approximation-with-documented-residual trade split's size-only gate made.
    Everything uncertain (unreadable page) fails OPEN."""
    for p in _candidate_pages(root):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            return True  # FAIL-OPEN (libs audit L-11): unreadable → not provably idle
        if _page_needs_repair(text):
            return True
    return False


def _has_substantive_body(body: str) -> bool:
    """True iff the body holds at least one line an atom could mark: non-empty,
    not a heading, not a pooled `[^N]:` footnote definition, not already a marker."""
    for ln in body.splitlines():
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        if _FOOTNOTE_DEF_RE.match(s) or memory_edit_verify._ATOM_MARKER_RE.match(s):
            continue
        return True
    return False


def atomize_has_work(root: Path) -> bool:
    """True iff some CURATED wiki page in `root` is still FREE-PROSE — no
    `^id [keywords: …]` atom marker yet — with a substantive body to mark
    (TRDD-3XS3PDCF follow-up).

    Mirrors the janitor-memory-atomize candidate scan exactly: RAW harness buffer
    notes are never candidates (`is_curated_wiki_page` is the coexistence
    discriminator), and a page carrying >=1 marker is skipped ("already
    atomized" per the skill's own memgrep filter — partial atomization is the
    agent's judgment, not the scheduler's). A candidate whose body has no
    markable line (headings + the empty Notes pool only) is the skill's
    "free-prose-leaf-no-distinct-facts" abstain case → not work. Unreadable
    pages fail OPEN. Marker shape SSOT: memory_edit_verify._ATOM_MARKER_RE."""
    for p in _candidate_pages(root):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            return True  # FAIL-OPEN (libs audit L-11): unreadable → not provably idle
        if not memory_scopes.is_curated_wiki_page(text):
            continue  # RAW buffer note — never an atomize candidate
        if any(memory_edit_verify._ATOM_MARKER_RE.match(ln) for ln in text.splitlines()):
            continue  # >=1 marker → the skill skips it ("already atomized")
        _fm, body = _split_page(text)
        if _has_substantive_body(body):
            return True
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
    if intervention == "repair":
        # STRUCTURAL page-shape gate (semantic residual documented on the function).
        return repair_has_work(root)
    if intervention == "atomize":
        # Free-prose curated pages without atom markers (the skill's own candidate scan).
        return atomize_has_work(root)
    # harvest: still a follow-up — BLOCKED until the coexistence-harvest model
    # stabilizes (TRDD-ab232dbd #231/#232); a predicate written now would
    # wrong-suppress against whichever model ships. conflict: semantic,
    # agent-discovered. Unknown chores: fail-open by default.
    return True
