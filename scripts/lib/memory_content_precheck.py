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
# REPAIR/ATOMIZE have STRUCTURAL prechecks (TRDD-3XS3PDCF follow-up — see each
# function for the exact predicate + its documented residual), and HARVEST has the
# skill's own step-1 buffer scan (un-mirrored raw notes via the watermark ledger —
# unblocked 2026-07-08 once the coexistence-mirror model shipped in v0.33.0 and its
# predicate stabilized). CONFLICT's *discovery* is genuinely SEMANTIC — but that is
# the librarian detector's job; the conflict PASS itself consumes the librarian's
# `### Conflict candidates` section ("Empty/absent → stop" is the skill's own
# precondition), so its due-ness IS mechanically precheckable (see
# conflict_has_work). With that, every one of the six chores is gated.
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

import hashlib
import re
from collections import Counter
from pathlib import Path

import memory_edit_verify  # sibling in scripts/lib/ — the SSOT for merge legality
import memory_refusals  # sibling in scripts/lib/ — the per-candidate refusal ledger (#131)
import memory_scopes  # sibling in scripts/lib/ (the caller puts lib on sys.path)
import memory_settings  # sibling in scripts/lib/ — the harvest watermark SSOT

# How long an "unchanged corpus" suppression stays valid before we re-dispatch anyway.
# Bounds the two cases where a byte-identical corpus could still hide real work: an agent
# that CRASHED before finishing its pass, and LLM non-determinism (a merge one run would
# have spotted and another missed). 7 days: long enough to kill the daily drain, short
# enough that no real merge waits more than a week on a corpus nobody is touching.
_DEFAULT_CONSOLIDATE_RECHECK_S = 7 * 86400.0


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


_TIER_RE = re.compile(r"^\s*tier:\s*([A-Za-z_-]+)\s*$", re.MULTILINE)

# The tiers a split can actually operate on. `component` is the one the split skill REFUSES:
# "one element = one page", so a component over the cap is not too big to split, it is
# MIS-TIERED — too big to be one element. That is a real finding and a cheap one.
_SPLITTABLE_TIERS = frozenset({"hub", "aspect"})


def _page_tier(path: Path) -> str:
    """The page's declared `tier:`, or "" when absent/unreadable. Reads the frontmatter only."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            head = fh.read(2048)
    except OSError:
        return ""
    m = _TIER_RE.search(head)
    return m.group(1).lower() if m else ""


def oversized_mistiered_pages(root: Path, *, max_bytes: int) -> list[tuple[Path, str]]:
    """Over-cap pages the split skill MUST refuse — `(path, tier)`, cheapest possible check.

    A page over the split cap whose tier is not splittable cannot be fragmented; the correct
    action is to RE-TIER it, which is a human/curator judgement rather than a split. Surfacing
    that from the scheduler costs a `stat` plus 2 KB of frontmatter, instead of the full agent
    context a dispatch spends only to reach the same refusal (issue #114).

    An UNREADABLE tier is deliberately NOT reported as mis-tiered: unknown is not refusable, and
    treating it as such would suppress a page that may well be splittable. It falls through to
    the normal dispatch path — the fail-open direction.
    """
    out: list[tuple[Path, str]] = []
    for p in _candidate_pages(root):
        try:
            if p.stat().st_size <= max_bytes:
                continue
        except OSError:
            continue  # unreadable size — handled fail-open by the caller, not here
        tier = _page_tier(p)
        if tier and tier not in _SPLITTABLE_TIERS:
            out.append((p, tier))
    return out


def split_has_work(root: Path, *, max_bytes: int) -> bool:
    """True iff some committed page in `root` is strictly larger than `max_bytes`
    (the split cap). Mirrors the split skill's `find -size +<cap>c` size gate with
    the SAME cap source (memory_settings split_max_bytes).

    The size gate is EXACTLY the right condition — the once-planned refinement to
    "over-cap AND splittable" is OBSOLETE (re-derived 2026-07-11, TRDD-3XS3PDCF) and must
    NOT be added: it would suppress real work. Since issues #57/#58, EVERY over-cap page
    gives the agent something to do, because `is_legal_split(..., oversized=True)` refuses
    only ONE case — `tier: component` — and that case is not an abstain either: the split
    skill SURFACES an over-cap component as a MIS-TIER to re-tier ("component over the cap —
    too big to be one element"). A seamless over-cap hub/aspect is likewise fail-safe
    splittable (the splitter synthesizes seams so it converges instead of abstaining
    forever). So "over-cap" already implies "the agent has work", and narrowing further
    would silently drop mis-tier reports on the floor.

    MEASURED CORRECTION 2026-07-28 (issue #114). The paragraph above is right that a mis-tier
    must not be dropped — and wrong that the AGENT is the only thing that can report it. An
    over-cap `tier: component` page is the ONE case the split skill must refuse, so every
    dispatch for it spends a full agent context (~260k tokens, twice in one session) to
    re-derive the same refusal, and nothing ever re-tiers the page, so it recurs forever. The
    report is not dropped — it MOVES to a channel that costs a `stat` and a frontmatter read
    (`oversized_mistiered_pages`, surfaced by the memory-maintenance detector). The agent is
    reserved for pages it can actually split.

    The caller guarantees max_bytes > 0 (see content_has_work fail-open)."""
    mistiered = {p for p, _t in oversized_mistiered_pages(root, max_bytes=max_bytes)}
    for p in _candidate_pages(root):
        if p in mistiered:
            continue  # refusable by construction — surfaced cheaply, never dispatched
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


def corpus_fingerprint(root: Path) -> str | None:
    """A cheap, stat-only fingerprint of the candidate corpus under `root`.

    sha256 over the sorted `(relpath, size, mtime_ns)` of every candidate page. No file is
    READ — only stat'd — so this is ~free even on a large corpus.

    Used by `consolidate_has_work` for the "nothing changed since we last looked" gate.
    Returns None on ANY stat error, which callers MUST treat as fail-open (dispatch): an
    unreadable corpus is not a provably-unchanged one.
    """
    h = hashlib.sha256()
    try:
        for p in sorted(_candidate_pages(root)):
            st = p.stat()
            h.update(f"{p.relative_to(root)}\0{st.st_size}\0{st.st_mtime_ns}\0".encode())
    except (OSError, ValueError):
        return None
    return h.hexdigest()


def consolidate_has_work(
    root: Path,
    *,
    last_fingerprint: str | None = None,
    stamp_age_s: float | None = None,
    recheck_after_s: float = _DEFAULT_CONSOLIDATE_RECHECK_S,
) -> bool:
    """True iff a CONSOLIDATE dispatch could plausibly do work on `root`.

    TWO gates, both zero-LLM, both fail-open:

    1. STRUCTURAL (TRDD-8UD3Q7K5, issue #64) — see below. Necessary, but NOT sufficient:
       both live scopes hold many `tier: component, type: reference` pages, so the gate
       passes, an agent spawns (~260k tokens), and then ABSTAINS on *subject*, which the
       structural gate never examined.

    2. UNCHANGED-CORPUS (TRDD-3XS3PDCF, 2026-07-11) — if the corpus fingerprint is
       IDENTICAL to the one stamped at the last dispatch, the agent has already read
       exactly this content and reached its verdict. Re-spawning it to re-read byte-identical
       pages cannot produce a different answer, so it is PROVABLY idle → suppress.

       This is the only sound way to gate consolidate. A "subject-overlap"/keyword proxy is
       NOT sound: the skill's own contract says a merge needs the *same subject*, "not merely
       sharing keywords" (its example: a `reference` "keychain location" and a `project`
       "rotator 429" share words but are different subjects), and conversely two same-subject
       pages may share no words at all — so a keyword gate would both over- and under-fire,
       and its under-fire silently destroys a real merge. Subject-sameness is the agent's
       human judgment; we do not guess it. We only observe that nothing has CHANGED.

       Any corpus mutation — a new page, an edit, a deletion — moves the fingerprint and
       re-arms the chore immediately. And the suppression EXPIRES after `recheck_after_s`
       (default 7 days), which bounds the two cases where "unchanged corpus" could hide real
       work: an agent that crashed before finishing, and LLM non-determinism (a merge one
       run would have seen and another missed).

    A None `last_fingerprint` (no stamp yet), an unreadable corpus, or a None `stamp_age_s`
    all fail OPEN — dispatch.

    Gate 1 detail: `is_legal_merge` refuses a merge unless both pages share the SAME
    `metadata.tier` AND that tier is in `_MERGEABLE_TIERS` (= {aspect, component} — a `hub`
    is an overview, not a leaf) AND both share the SAME `metadata.type`. So a structural
    merge pair exists iff >=2 candidate pages share the same (tier, type) key with a
    mergeable tier. If NO such pair exists, `is_legal_merge` would categorically refuse
    EVERY pair, the agent can only abstain, and the dispatch is provably idle → suppress.

    Cost: one rglob over the shared candidate SSOT + a tiny leading-frontmatter parse
    per page (no body read, no YAML engine, no LLM, no agent). Uses the SAME SSOTs the
    EXECUTOR uses — `memory_scopes.iter_note_files` (excludes `.maint-staging/`,
    `user-mem/`, generated/index basenames, `-proposed.md` reports) and
    `memory_edit_verify.parse_frontmatter` / `_MERGEABLE_TIERS` — so the precheck and
    the commit-time `is_legal_merge` can never drift (cf. TRDD-87935f21: one source of
    truth for merge legality)."""
    # Gate 2 FIRST — it is stat-only, so it is strictly cheaper than gate 1's per-page
    # frontmatter parse, and on a settled corpus it is the one that fires.
    if last_fingerprint and stamp_age_s is not None and stamp_age_s < recheck_after_s:
        current = corpus_fingerprint(root)
        if current is not None and current == last_fingerprint:
            return False  # byte-identical corpus already examined → provably idle

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
    if memory_edit_verify.atom_desc_violations(text):
        return True  # atom desc missing/unquoted-prose/over-cap — verify_repair's own bar
        # (TRDD-3SOO1RWE: extending the precheck is safe ONLY because the repair skill
        # now backfills descs — the WN7M829Y scope note forbade flagging defects the
        # pass cannot fix; this one it can, via the same SSOT check.)
    return False


def repair_has_work(root: Path, *, scope: str | None = None, now: int | None = None) -> bool:
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
    Everything uncertain (unreadable page) fails OPEN.

    REFUSAL FILTER (issue #124, on the ledger from #131). A page can carry a defect this pass
    cannot make STICK — the reported case is a frontmatter shape an external writer converges on,
    but the class is general: anything a writer outside the janitor's control re-imposes. Such a
    page re-flags every run, and because the ranking is by defect count it is picked ahead of pages
    that CAN be fixed — so the unfixable defect does not merely waste a pass, it starves the
    fixable ones. Once the agent records a refusal on that page, the page stops being a candidate
    until its own bytes change — which is exactly when the question is worth re-asking, including
    when the external writer rewrites it. `scope` is required to read the ledger; without it the
    filter is not applied, never a suppression."""
    for p in _candidate_pages(root):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            return True  # FAIL-OPEN (libs audit L-11): unreadable → not provably idle
        if not _page_needs_repair(text):
            continue
        if scope is None:
            return True  # cannot read the ledger ⇒ never suppress
        if not memory_refusals.is_refused("repair", scope, root, [p], now=now):
            return True  # a defect nobody has ruled unfixable
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


# The generated top-level basenames the harvest skill's own buffer scan excludes.
# Kept as a module constant so the precheck and any future caller share one list.
_HARVEST_EXCLUDED_NAMES = frozenset({"MEMORY.md", "memory-index.md", "memory-reorg-proposed.md"})

# The librarian-written section heading + empty-sentinel the conflict skill reads
# (memory-librarian.py `_render_scope_section` writes both — writer/reader parity).
_CONFLICT_SECTION_HEADING = "### Conflict candidates"
_NO_CANDIDATES_SENTINEL = "- (none)"


# A conflict bullet, as the librarian writes it: "- topic `<tag>`: <a> vs <b>" (writer/reader
# parity with memory-librarian.py `_render_scope_section`). The two paths are the CANDIDATE, which
# is what the refusal ledger is keyed on.
_CONFLICT_PAIR_RE = re.compile(r"^-\s+topic\s+`[^`]*`:\s*(?P<a>\S+)\s+vs\s+(?P<b>\S+)\s*$")


def conflict_pairs(root: Path) -> list[tuple[str, str]]:
    """Every surfaced conflict candidate pair in the scope's proposal file, in order.

    Split out of `conflict_has_work` so the pair identity — not just the bullet count — is available
    to the refusal ledger (issue #131). A bullet that does not parse is deliberately returned as a
    `("", "")` sentinel by the caller's logic rather than dropped: an unparseable candidate is not a
    refused one, and dropping it would suppress the chore on a rendering change.
    """
    out: list[tuple[str, str]] = []
    try:
        text = (root / "memory-reorg-proposed.md").read_text(encoding="utf-8")
    except OSError:
        return out
    in_section = False
    for ln in text.splitlines():
        s = ln.strip()
        if s == _CONFLICT_SECTION_HEADING:
            in_section = True
            continue
        if in_section and s.startswith("#"):
            in_section = False
            continue
        if in_section and s.startswith("- ") and s != _NO_CANDIDATES_SENTINEL:
            m = _CONFLICT_PAIR_RE.match(s)
            out.append((m.group("a"), m.group("b")) if m else ("", ""))
    return out


def conflict_has_work(root: Path, *, scope: str | None = None, now: int | None = None) -> bool:
    """True iff the scope's `memory-reorg-proposed.md` carries at least one REAL
    conflict candidate (TRDD-3XS3PDCF follow-up — the last precheckable chore).

    The conflict PASS is not self-discovering: its sole candidate source is the
    librarian's proposal file — the skill's own precondition 3 reads the
    `### Conflict candidates` section and mandates "Empty/absent → stop". So the
    pass's due-ness is mechanically checkable even though conflict DISCOVERY is
    semantic (the librarian detector does that for free on the heartbeat):

    - file ABSENT → the skill would stop → provably idle → False.
    - only `- (none)` sentinel bullets (the librarian's empty marker) → False.
    - ANY other `- ` bullet inside a Conflict-candidates section → True (dispatch;
      the agent still applies its own scope/legality judgment per pair).
    - file present but UNREADABLE → True (fail-open — not provably idle).

    Live evidence: a heartbeat conflict pass on 2026-07-08 abstained on the empty
    section at 260,931 tokens — the same no-op class as the other gates.

    REFUSAL FILTER (issue #131, #106). The librarian re-lists a pair every run, including one the
    agent already judged and declined — so a non-empty list is not the same thing as unfinished
    work. A pair carrying a live refusal (same two pages, byte-identical, inside the TTL) is skipped;
    the chore is idle only when EVERY surfaced pair is refused. `scope` is required to read the
    ledger, so without it the filter is simply not applied — never a suppression."""
    proposal = root / "memory-reorg-proposed.md"
    if not proposal.is_file():
        return False  # "Empty/absent → stop" — absence is the skill's own idle case
    try:
        proposal.read_text(encoding="utf-8")
    except OSError:
        return True  # present but unreadable → FAIL-OPEN (libs audit L-11)
    for a, b in conflict_pairs(root):
        if not a or not b:
            return True  # an unparseable bullet is NOT a refused one — fail open
        if scope is None:
            return True  # cannot read the ledger ⇒ never suppress
        if not memory_refusals.is_refused("conflict", scope, root, [root / a, root / b], now=now):
            return True  # a candidate nobody has ruled on yet
    return False


def harvest_has_work(scope: str, root: Path) -> bool:
    """True iff some RAW buffer note in `root` is not yet (or no longer) mirrored
    into the curated wiki (TRDD-3XS3PDCF follow-up — UNBLOCKED 2026-07-08 once the
    coexistence-mirror harvest model shipped in v0.33.0 and ran live).

    Mirrors the janitor-memory-harvest skill's candidate scan EXACTLY (step 1 of
    the skill): TOP-LEVEL `<root>/*.md` only (NOT recursive — the skill uses
    `root.glob("*.md")`, so a nested note is never a harvest candidate and must not
    make the precheck claim work the skill won't do), minus the generated
    basenames; a CURATED page (`is_curated_wiki_page` True — the coexistence
    discriminator) is never buffer material; a raw note already watermarked with
    unchanged content (`harvest_note_is_mirrored`) is already mirrored. Anything
    else is exactly one un-mirrored buffer note = real work. Unreadable notes and
    watermark-read failures fail OPEN (harvest re-mirroring is additive and safe,
    so a wrong dispatch is a no-op; a wrong suppress silently breaks the chore).

    Live evidence for the gate: two heartbeat harvest passes on 2026-07-08
    abstained "nothing due" at 257,826 + 266,125 tokens — the exact no-op class
    this module exists to kill."""
    try:
        candidates = sorted(root.glob("*.md"))
    except OSError:
        return True  # can't even list → not provably idle (FAIL-OPEN)
    for p in candidates:
        if p.name in _HARVEST_EXCLUDED_NAMES:
            continue  # harness/index files the skill never mirrors
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            return True  # FAIL-OPEN (libs audit L-11): unreadable → not provably idle
        if memory_scopes.is_curated_wiki_page(text):
            continue  # already curated → not a buffer note
        if not memory_settings.harvest_note_is_mirrored(scope, str(root), p.name, text):
            return True  # an un-mirrored (or edited-since-mirror) raw buffer note
    return False


def content_has_work(
    intervention: str,
    root: Path,
    *,
    split_max_bytes: int,
    scope: str | None = None,
    last_fingerprint: str | None = None,
    stamp_age_s: float | None = None,
) -> bool:
    """True iff `intervention` has actual work on the `root` corpus.

    FAIL-OPEN: returns True for every chore WITHOUT a cheap, exact precheck, for
    SPLIT when the cap is non-positive, for HARVEST when the caller supplied no
    `scope` (the watermark ledger is keyed per (scope, root) — without the scope we
    can't read it, so we never suppress), and for CONSOLIDATE when the caller supplied
    no dispatch stamp. A chore is suppressed ONLY when its idleness is cheaply PROVEN;
    otherwise the scheduler keeps its existing cadence-only behavior."""
    if intervention == "split":
        if split_max_bytes <= 0:
            return True  # cap unreadable/disabled → fail-open (do not suppress)
        return split_has_work(root, max_bytes=split_max_bytes)
    if intervention == "consolidate":
        # STRUCTURAL gate (subject-sameness stays agent-discovered) + the UNCHANGED-CORPUS
        # gate: a byte-identical corpus was already examined, so re-spawning cannot yield a
        # different verdict. Absent stamp → fail-open (both args default to None).
        return consolidate_has_work(
            root, last_fingerprint=last_fingerprint, stamp_age_s=stamp_age_s
        )
    if intervention == "repair":
        # STRUCTURAL page-shape gate (semantic residual documented on the function).
        # `scope` also unlocks the per-page refusal filter, so a defect proven unfixable
        # stops out-ranking the fixable ones (#124).
        return repair_has_work(root, scope=scope)
    if intervention == "atomize":
        # Free-prose curated pages without atom markers (the skill's own candidate scan).
        return atomize_has_work(root)
    if intervention == "harvest":
        # Un-mirrored raw buffer notes (the skill's own step-1 scan). Needs the
        # scope to key the watermark ledger; scope unknown → fail-open.
        if scope is None:
            return True
        return harvest_has_work(scope, root)
    if intervention == "conflict":
        # The pass consumes the librarian's surfaced candidates ("Empty/absent →
        # stop" is the skill's own precondition); discovery stays semantic and
        # stays the librarian's job. `scope` also unlocks the per-candidate refusal
        # filter — without it the gate keeps its old bullet-count behavior (#131).
        return conflict_has_work(root, scope=scope)
    # Unknown chores: fail-open by default.
    return True
