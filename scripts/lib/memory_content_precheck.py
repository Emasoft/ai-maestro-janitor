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
# conflict_has_work). With that, every one of the seven chores is gated
# (RETRO-LESSON joined with its own structural gate — TRDD-J3ZH3RSI).
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


def page_stats(root: Path) -> dict[str, list[int]] | None:
    """`{relpath: [size, mtime_ns]}` for every candidate page — the STAMPED form of
    `corpus_fingerprint` (TRDD-9MQ25PNH).

    Same stat-only walk and same cost as the digest; it just keeps the per-page detail
    instead of collapsing it. That detail is what lets the gate ask *which* pages moved,
    so a change confined to an already-judged group can be distinguished from a change
    anywhere else — the whole point of the refusal filter below.

    Returns None on ANY stat error, which callers MUST treat as fail-open (dispatch):
    an unreadable corpus is not a provably-unchanged one.
    """
    out: dict[str, list[int]] = {}
    try:
        for p in sorted(_candidate_pages(root)):
            st = p.stat()
            out[str(p.relative_to(root))] = [st.st_size, st.st_mtime_ns]
    except (OSError, ValueError):
        return None
    return out


def changed_pages(current: dict[str, list[int]], last: dict[str, list[int]]) -> set[str]:
    """Root-relative paths that were added, removed, or whose stat moved. PURE."""
    changed = {rel for rel, st in current.items() if last.get(rel) != st}
    changed.update(rel for rel in last if rel not in current)
    return changed


def refusal_covered_pages(
    root: Path, scope: str, *, now: int | None = None
) -> set[str]:
    """Root-relative paths covered by a LIVE consolidate refusal (TRDD-9MQ25PNH).

    A refusal is keyed on a whole candidate GROUP — the librarian's aggregation bullets are
    groups of 2/4/6 pages, and `candidate_key` joins their sorted relpaths. So membership
    cannot be answered by `is_refused([one_page])`: that would build a one-element key which
    matches no group. We re-validate each stored group through `memory_refusals.refusal`
    (which re-checks BOTH the TTL and the group's `content_hash`) and, only if the group is
    still live, treat its members as covered.

    The content_hash re-check is what makes this self-correcting: edit any page in a refused
    group and the whole group's refusal stops matching, so none of its members count as
    covered, the edit shows up as an uncovered change, and the chore re-arms — no expiry
    bookkeeping of our own.
    """
    covered: set[str] = set()
    for key in memory_refusals.read("consolidate", scope, root):
        rels = key.split("|")
        if memory_refusals.refusal(
            "consolidate", scope, root, [root / r for r in rels], now=now
        ):
            covered.update(rels)
    return covered


def group_has_unjudged_pair(
    root: Path, scope: str, pages: list[Path], *, now: int | None = None
) -> bool:
    """True iff some PAIR within this (tier, type) group has not been judged-and-declined
    by a live consolidate refusal — the group-level refusal semantics BOTH the scheduler
    gate and the candidates CLI must share (review 2026-08-08, two findings).

    Why pair-granular: a merge fuses exactly TWO pages, and the merge-protocol records an
    abstain keyed on the judged PAIR. The CLI used to filter on the FULL group's exact key
    — which a pair-keyed refusal never matches, so any 3+-member group re-listed forever.
    The scheduler meanwhile checked no refusals in its structural gate at all, so it could
    dispatch when the CLI would print nothing. One rule fixes both: a pair (x, y) is JUDGED
    iff some live refused set contains both x and y (an exact-group refusal therefore
    covers all its pairs); a group is a candidate only while an UNJUDGED pair remains —
    which is exactly when there is real judgment work left.

    Fail-open: unresolvable relpaths or an unreadable ledger count as unjudged (dispatch).
    Each stored refusal is re-validated through `memory_refusals.refusal` (TTL +
    content_hash), so editing any member page revives its pairs automatically."""
    rels: list[str] = []
    for p in pages:
        try:
            rels.append(str(p.relative_to(root)))
        except ValueError:
            return True  # cannot key it → cannot prove it judged → dispatch
    live_sets: list[set[str]] = []
    for key in memory_refusals.read("consolidate", scope, root):
        members = key.split("|")
        if memory_refusals.refusal(
            "consolidate", scope, root, [root / r for r in members], now=now
        ):
            live_sets.append(set(members))
    for i in range(len(rels)):
        for j in range(i + 1, len(rels)):
            a, b = rels[i], rels[j]
            if not any(a in s and b in s for s in live_sets):
                return True
    return False


def consolidate_has_work(
    root: Path,
    *,
    last_stats: dict[str, list[int]] | None = None,
    stamp_age_s: float | None = None,
    recheck_after_s: float = _DEFAULT_CONSOLIDATE_RECHECK_S,
    scope: str | None = None,
    now: int | None = None,
    max_bytes: int = 0,
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

    3. REFUSAL FILTER (TRDD-9MQ25PNH) — gate 2 above suppresses only a corpus that has not
       moved AT ALL, which the other memory chores break constantly by writing to this same
       corpus. So when pages HAVE moved, every moved page is checked for membership of a
       live consolidate refusal; if all of them sit inside groups the agent already judged
       and declined, there is still nothing new to look at → suppress. Needs `scope` to read
       the ledger; without it the filter is simply not applied — never a suppression.

    A None `last_stats` (no stamp yet), an unreadable corpus, or a None `stamp_age_s`
    all fail OPEN — dispatch.

    Gate 1 detail: `is_legal_merge` refuses a merge unless both pages share the SAME
    `metadata.tier` AND that tier is in `_MERGEABLE_TIERS` (= {aspect, component} — a `hub`
    is an overview, not a leaf) AND both share the SAME `metadata.type`. So a structural
    merge pair exists iff >=2 candidate pages share the same (tier, type) key with a
    mergeable tier. If NO such pair exists, `is_legal_merge` would categorically refuse
    EVERY pair, the agent can only abstain, and the dispatch is provably idle → suppress.

    4. UNMERGEABLE-BY-SIZE (janitor#210). A structural pair (gate 1) is not necessarily a
       LEGAL one: two pages whose combined byte size exceeds the page cap can never be
       merged — the result would be over-cap on its first byte, a fact the corpus's own
       arithmetic proves without reading a single word of either page. This candidate is
       worse than a merely-refused one: refusal ledger coverage (TRDD-9MQ25PNH) requires
       the pages' content_hash to stay unchanged, but these pages only ever GROW (any
       other memory chore editing either one invalidates the refusal), so a byte-size-
       impossible pair can re-open the ~189k-token dispatch forever even though the
       arithmetic that dooms it never changes. When `max_bytes > 0`, a (tier, type) group
       counts as a real candidate only if its two SMALLEST pages fit together under the
       cap — the best case for that group, so if even they don't fit, nothing in it does.
       `max_bytes <= 0` (cap unreadable) falls back to gate 1's plain count>=2 check,
       exactly as before this fix — the size filter is strictly additive, never a new way
       to fail open into a false suppress.

    Cost: one rglob over the shared candidate SSOT + a tiny leading-frontmatter parse
    per page (no body read, no YAML engine, no LLM, no agent). Uses the SAME SSOTs the
    EXECUTOR uses — `memory_scopes.iter_note_files` (excludes `.maint-staging/`,
    `user-mem/`, generated/index basenames, `-proposed.md` reports) and
    `memory_edit_verify.parse_frontmatter` / `_MERGEABLE_TIERS` — so the precheck and
    the commit-time `is_legal_merge` can never drift (cf. TRDD-87935f21: one source of
    truth for merge legality)."""
    # Gate 2 FIRST — it is stat-only, so it is strictly cheaper than gate 1's per-page
    # frontmatter parse, and on a settled corpus it is the one that fires.
    if last_stats and stamp_age_s is not None and stamp_age_s < recheck_after_s:
        current = page_stats(root)
        if current is not None:
            moved = changed_pages(current, last_stats)
            if not moved:
                return False  # byte-identical corpus already examined → provably idle
            # REFUSAL FILTER (TRDD-9MQ25PNH). A change confined to groups the agent has
            # ALREADY judged and declined is not new work. Without this, any byte anywhere
            # re-opened a full ~279k dispatch — including the agent's own edits, since the
            # other memory chores write to this same corpus.
            #
            # Compared PER PAGE rather than as one narrowed digest, deliberately: the stamp
            # is taken at DISPATCH time (memory-maintenance.py, beside mark_ran), BEFORE the
            # agent records its refusals. A digest over "pages not currently refused" would
            # therefore differ from its own stamp the moment a refusal is recorded, buying
            # one spurious dispatch after every productive round. Recording a refusal touches
            # no file, so a per-page stat map is unchanged and this gate stays correctly shut.
            if scope is not None and moved <= refusal_covered_pages(root, scope, now=now):
                return False  # every moved page sits in a live, still-matching refusal

    # Grouped + judged by the shared (janitor#227) SSOT helpers below — gate 1
    # (structural pair) and gate 4 (UNMERGEABLE-BY-SIZE, #210) both live in
    # `consolidate_group_defect` now, so the scheduler's boolean gate and the
    # CANDIDATE-LISTING CLI can never disagree on which group qualifies.
    by_key = _group_candidates_by_tier_type(root)
    if by_key is None:
        # FAIL-OPEN (libs audit L-11): an unreadable page could be one half of a
        # mergeable pair, so treating the corpus as idle could wrongly suppress the chore.
        return True
    # Refusal-aware, same rule as the CLI (review 2026-08-08): a group whose every pair is
    # already judged-and-declined is not work, and dispatching on it spawns an agent whose
    # candidate list is empty — the #227 loop. `scope is None` skips the filter (fail-open),
    # matching gate 3's contract: no scope, no ledger, never a suppression.
    return any(
        consolidate_group_defect(pages, max_bytes=max_bytes)
        and (scope is None or group_has_unjudged_pair(root, scope, pages, now=now))
        for pages in by_key.values()
    )


def _group_candidates_by_tier_type(
    root: Path,
) -> dict[tuple[object, object], list[Path]] | None:
    """Every candidate page in `root`, grouped by `(tier, type)` — the structural
    grouping gate 1 of `consolidate_has_work` and the group-listing CLI share
    (janitor#227). Only tiers in `memory_edit_verify._MERGEABLE_TIERS` are grouped
    (a `hub` — or a tier-less raw note — is never a legal-merge leaf).

    Returns `None` on ANY unreadable page — the FAIL-OPEN sentinel every caller here
    must treat as "cannot prove this corpus is idle" (libs audit L-11)."""
    by_key: dict[tuple[object, object], list[Path]] = {}
    for p in _candidate_pages(root):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            return None
        fm = memory_edit_verify.parse_frontmatter(text)
        tier = fm.get("tier")
        if tier not in memory_edit_verify._MERGEABLE_TIERS:
            continue  # hub / tier-less raw note → never a legal-merge leaf
        key = (tier, fm.get("type"))
        by_key.setdefault(key, []).append(p)
    return by_key


def consolidate_group_defect(pages: list[Path], *, max_bytes: int = 0) -> str:
    """The SINGLE-SOURCE reason slug for why a `(tier, type)` GROUP of candidate
    pages is a structural consolidate candidate (janitor#227 follow-up) — mirrors
    gate 1 (structural pair exists) + gate 4 (UNMERGEABLE-BY-SIZE, #210) of
    `consolidate_has_work`. `""` when the group does not qualify: fewer than 2
    members, or (when `max_bytes>0`) even its two SMALLEST members cannot fit under
    the split cap combined — the best case for the group, so if even they don't fit,
    nothing in it does.

    Consolidate's candidate unit is a GROUP, not a single page (see
    `refusal_covered_pages`) — this is why it takes `pages`, not `text` like
    `repair_defect`/`atomize_defect`. Slug: `same-tier-type`.

    DELIBERATE deviation from the pre-#227 code (review 2026-08-08): the old inline
    gate fail-opened (dispatched) on a stat() OSError even for a SINGLE-member group;
    here a singleton returns "" before any stat. A one-page group cannot yield a merge
    under any outcome, so that old fail-open dispatched a provably idle agent — the
    exact waste #227 exists to remove. Groups of >=2 keep the stat fail-open below."""
    if len(pages) < 2:
        return ""
    if max_bytes <= 0:
        return "same-tier-type"  # cap unknown → gate 1's plain count>=2 check (unchanged)
    try:
        sizes = sorted(p.stat().st_size for p in pages)
    except OSError:
        return "same-tier-type"  # FAIL-OPEN: unknown size can't prove a pair impossible
    if sizes[0] + sizes[1] > max_bytes:
        return ""  # even the two smallest can't fit together — not a real candidate
    return "same-tier-type"


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


def _footer_heading_line(text: str) -> int | None:
    """0-based line index of the EARLIEST footer heading — `## Applies to`, `## Governed
    by`, or the Notes heading (any spelling `memory_edit_verify._LESSONS_HEADING`'s own
    match accepts) — fence-aware, or None when the page carries none of them. Mirrors the
    memgrep crate's `footer_section_line` (janitor#250) so this precheck and `add-atom`'s
    insertion boundary can never disagree about where the footer starts."""
    in_fence = False
    for i, line in enumerate(text.splitlines()):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if stripped.startswith("#"):
            low = stripped.lower()
            heading_text = low.lstrip("#").strip()
            if (
                heading_text == "applies to"
                or heading_text == "governed by"
                or "notes and lessons learned" in low
                or "lessons learned" in low
            ):
                return i
    return None


def repair_defect(text: str) -> str:
    """The SINGLE-SOURCE repair-candidacy predicate (janitor#227): return the SHORT,
    stable reason slug for the FIRST structurally-detectable defect this page exhibits
    from the janitor-memory-repair checklist, or `""` when the page is clean.

    This is the ONLY place that decides "does this page need repair" — both the
    SCHEDULER's boolean gate (`_page_needs_repair`, kept as a thin wrapper below) and
    the CANDIDATE-LISTING CLI (`scripts/memory_candidates_cli.py`) call this, so a page
    the scheduler flags can never be a page the candidate lister fails to name (the
    janitor#227 bug: `memgrep lint` and this precheck disagreed, so the repair skill
    found nothing to work and the chore re-dispatched forever).

    Every check mirrors a bar `verify_repair` (or the skill's own diagnosis list)
    enforces, via the same SSOT constants — so the precheck and the commit-time
    verifier can never drift. Slugs are printed (by the CLI) and so MUST stay stable:
    `no-frontmatter`, `missing-key:<key>`, `illegal-tier`, `no-notes-heading`,
    `nested-only-dates`, `inverted-tier-shape`, `atom-desc`, `superseded-misplaced`,
    `atom-after-footer`."""
    fm_block, _body = _split_page(text)
    if fm_block is None:
        return "no-frontmatter"  # no/unclosed frontmatter → invisible to ranked recall
    meta = memory_edit_verify.parse_frontmatter(text)
    for key in memory_edit_verify._REQUIRED_FM_KEYS:
        if not str(meta.get(key, "")).strip():
            return f"missing-key:{key}"  # missing/empty required key — verify_repair's own bar
    if str(meta.get("tier", "")).strip() not in memory_edit_verify._VALID_TIERS:
        return "illegal-tier"  # tier outside the legal set → repair re-tags it
    if memory_edit_verify._LESSONS_HEADING not in text:
        return "no-notes-heading"  # the standing Notes section is mandatory on every page
    for pat in _TOP_LEVEL_DATE_RES:
        if not pat.search(fm_block):
            return "nested-only-dates"  # ocd/lmd present only NESTED → placement-normalization work
    tier = str(meta.get("tier", "")).strip()
    has_applies = "## Applies to" in text
    has_governed = "## Governed by" in text
    if tier in ("aspect", "hub") and has_governed and not has_applies:
        return "inverted-tier-shape"  # a radiator built as a receiver
    if tier == "component" and has_applies:
        return "inverted-tier-shape"  # a receiver that radiates (the mirror inversion)
    if memory_edit_verify.atom_desc_violations(text):
        return "atom-desc"  # atom desc missing/unquoted-prose/over-cap — verify_repair's own bar
        # (TRDD-3SOO1RWE: extending the precheck is safe ONLY because the repair skill
        # now backfills descs — the WN7M829Y scope note forbade flagging defects the
        # pass cannot fix; this one it can, via the same SSOT check.)
    lines = text.splitlines()
    # An atom marker that landed AT OR AFTER the earliest footer heading (`## Applies
    # to` / `## Governed by` / Notes) — janitor#250: the OLD `add-atom` anchor spliced
    # only before Notes, so a page with link sections ahead of Notes got the new atom
    # stuck INSIDE the last link section, where `--in "Governed by"` misreads it as part
    # of that section. Flag it so the repair skill can move it back above the footer.
    footer_idx = _footer_heading_line(text)
    if footer_idx is not None and any(
        i >= footer_idx and memory_edit_verify._ATOM_MARKER_PROPS_RE.match(ln)
        for i, ln in enumerate(lines)
    ):
        return "atom-after-footer"
    # Mis-placed superseded atoms (TRDD-QKWU26ZG — mirrors memgrep's two lint WARNs,
    # `superseded-atom-no-delimiter-heading` / `superseded-atom-above-delimiter`).
    # Safe to flag for the same TRDD-3SOO1RWE reason: the repair skill now performs
    # the verbatim move-below-the-delimiter fix, landing in the same change as this.
    sup_idx = [
        i for i, ln in enumerate(lines)
        if (m := memory_edit_verify._ATOM_MARKER_PROPS_RE.match(ln))
        and _SUPERSEDED_STATUS_RE.search(m.group(2))
    ]
    if sup_idx:
        heading = next(
            (i for i, ln in enumerate(lines) if ln.strip() == _SUPERSEDED_HEADING), None
        )
        if heading is None:
            return "superseded-misplaced"  # superseded atoms but no `## Superseded` section at all
        if any(i < heading for i in sup_idx):
            return "superseded-misplaced"  # a superseded atom still sits ABOVE the delimiter
    return ""


def _page_needs_repair(text: str) -> bool:
    """True iff this page exhibits a STRUCTURALLY-detectable defect — thin boolean
    wrapper over `repair_defect`, the single-source predicate (janitor#227)."""
    return bool(repair_defect(text))


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


# The superseded status value, tolerant of the `superseeded` misspelling exactly as
# memgrep's own parser is (a misspelled retirement must not be invisible). Shared by
# the retro-lesson precheck and the repair delimiter check (TRDD-QKWU26ZG).
_SUPERSEDED_STATUS_RE = re.compile(r"status\s*:\s*supers?e+ded")
# The canonical readability delimiter (SSOT spelling: memgrep's superseded_heading_line).
_SUPERSEDED_HEADING = "## Superseded"


def retro_lesson_has_work(root: Path) -> bool:
    """True iff some CURATED wiki page in `root` carries an atom marker that is
    `status:superseded` but has NO `superseded-by:` forward pointer — the exact
    structural signature of "superseded-but-not-yet-lesson-form" (TRDD-J3ZH3RSI,
    parent duty 9).

    WHY this discriminator: `memgrep add-lesson --supersedes --retire-atom` is the
    ONE conversion path, and it stamps `status: superseded, superseded-by:<lesson-id>`
    together — so a pointer-less superseded atom is one that never went through the
    conversion. The pointer is also what the retro skill MUST complete (memory.rs's
    retire step is idempotent-skipped when a `status:` prop already exists, so the
    skill appends the pointer itself via the repair-op txn) — which is what makes
    this precheck CONVERGE instead of re-firing forever on a converted atom.
    Misspelling tolerance mirrors memgrep's own parser (`superseeded` accepted on
    both the status value and the pointer key). Unreadable pages fail OPEN; RAW
    buffer notes are never candidates (coexistence discriminator)."""
    for p in _candidate_pages(root):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            return True  # FAIL-OPEN: unreadable → not provably idle
        if not memory_scopes.is_curated_wiki_page(text):
            continue  # RAW buffer note — never a retro-lesson candidate
        for ln in text.splitlines():
            m = memory_edit_verify._ATOM_MARKER_PROPS_RE.match(ln)
            if not m:
                continue
            props = m.group(2)
            superseded = bool(_SUPERSEDED_STATUS_RE.search(props))
            has_pointer = bool(re.search(r"supers?e+ded-by\s*:", props))
            if superseded and not has_pointer:
                return True
    return False


def atomize_defect(text: str) -> str:
    """The SINGLE-SOURCE atomize-candidacy predicate (janitor#227 follow-up — mirrors
    `repair_defect`): return the SHORT, stable reason slug for the FIRST
    structurally-detectable reason this page is an atomize candidate, or `""` when it
    is not (RAW buffer note, already atomized, or no substantive body to mark).

    This is the ONLY place that decides "is this page an atomize candidate" — both the
    SCHEDULER's boolean gate (`atomize_has_work`, kept as a thin caller below) and the
    CANDIDATE-LISTING CLI (`scripts/memory_candidates_cli.py`) call this, so a page the
    scheduler flags can never be a page the candidate lister fails to name (the same
    janitor#227 disagreement class `repair_defect` exists to prevent — the scheduler and
    `memgrep lint` used to disagree, so the atomize skill's own memgrep-based scan could
    likewise diverge from `atomize_has_work`).

    Mirrors the janitor-memory-atomize candidate scan exactly: RAW harness buffer notes
    are never candidates (`is_curated_wiki_page` is the coexistence discriminator), and
    a page carrying >=1 marker is skipped ("already atomized" per the skill's own
    memgrep filter — partial atomization is the agent's judgment, not the scheduler's).
    A candidate whose body has no markable line (headings + the empty Notes pool only)
    is the skill's "free-prose-leaf-no-distinct-facts" abstain case → not work. Marker
    shape SSOT: memory_edit_verify._ATOM_MARKER_RE. Slug: `free-prose`."""
    if not memory_scopes.is_curated_wiki_page(text):
        return ""  # RAW buffer note — never an atomize candidate
    if any(memory_edit_verify._ATOM_MARKER_RE.match(ln) for ln in text.splitlines()):
        return ""  # >=1 marker → the skill skips it ("already atomized")
    _fm, body = _split_page(text)
    if not _has_substantive_body(body):
        return ""  # free-prose-leaf-no-distinct-facts — nothing markable
    return "free-prose"


def atomize_has_work(root: Path, *, scope: str | None = None, now: int | None = None) -> bool:
    """True iff some CURATED wiki page in `root` is an atomize candidate per
    `atomize_defect` (TRDD-3XS3PDCF follow-up). Unreadable pages fail OPEN.

    REFUSAL FILTER (janitor#212 — the same TRDD-9MQ25PNH/#124 mechanism `repair_has_work`
    already carries). A page can look markable to `atomize_defect`'s STRUCTURAL check
    (non-empty, non-heading prose) and still be genuinely un-atomizable in the skill's own
    semantic judgment — a boilerplate bootstrap stub is the measured case ("This is the entry
    point... replace this stub the first time you write real knowledge here"). Without a
    refusal read-back such a page re-qualifies as a candidate on EVERY precheck call
    forever, because nothing about its bytes ever changes: the marker keeps re-firing a
    full agent dispatch to re-discover the same "nothing to atomize here" verdict. Once a
    refusal is recorded for that exact page, it stops being a candidate until its own
    bytes change. `scope` is required to read the ledger; without it the filter is simply
    not applied — never a suppression (same fail-open contract as repair's)."""
    for p in _candidate_pages(root):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            return True  # FAIL-OPEN (libs audit L-11): unreadable → not provably idle
        if not atomize_defect(text):
            continue
        if scope is None:
            return True  # cannot read the ledger ⇒ never suppress
        if not memory_refusals.is_refused("atomize", scope, root, [p], now=now):
            return True  # a candidate nobody has judged un-atomizable yet
    return False


# The generated top-level basenames the harvest skill's own buffer scan excludes.
# Kept as a module constant so the precheck and any future caller share one list.
_HARVEST_EXCLUDED_NAMES = frozenset({"MEMORY.md", "memory-index.md", "memory-reorg-proposed.md"})

# The librarian-written section heading + empty-sentinel the conflict skill reads
# (memory-librarian.py `_render_scope_section` writes both — writer/reader parity).
_CONFLICT_SECTION_HEADING = "### Conflict candidates"
_NO_CANDIDATES_SENTINEL = "- (none)"

# The librarian writes ONE combined proposal (into the LOCAL root — "LOCAL is always
# first", memory-librarian.py `_resolve_scope_dirs`), with a `## <SCOPE> scope` heading
# per scope (memory-librarian.py `_render_scope_section`: `f"## {report.scope} scope"`).
# Matched against a STRIPPED line, so leading/trailing whitespace never breaks it.
_SCOPE_HEADING_RE = re.compile(r"^##\s+(?P<scope>\S+)\s+scope$")


# A conflict bullet, as the librarian writes it: "- topic `<tag>`: <a> vs <b>" (writer/reader
# parity with memory-librarian.py `_render_scope_section`). The two paths are the CANDIDATE, which
# is what the refusal ledger is keyed on.
_CONFLICT_PAIR_RE = re.compile(r"^-\s+topic\s+`[^`]*`:\s*(?P<a>\S+)\s+vs\s+(?P<b>\S+)\s*$")


def conflict_pairs(root: Path, scope: str | None = None) -> list[tuple[str, str]]:
    """Every surfaced conflict candidate pair in the scope's proposal file, in order.

    Split out of `conflict_has_work` so the pair identity — not just the bullet count — is available
    to the refusal ledger (issue #131). A bullet that does not parse is deliberately returned as a
    `("", "")` sentinel by the caller's logic rather than dropped: an unparseable candidate is not a
    refused one, and dropping it would suppress the chore on a rendering change.

    SCOPED (issue #162): the librarian writes ONE combined proposal, with a `### Conflict
    candidates` block PER `## <SCOPE> scope` heading, into the LOCAL root. The parser used to be
    scope-blind INSIDE the file — it opened on any `### Conflict candidates` heading regardless of
    which `## <SCOPE> scope` section it sat under — so a LOCAL-root read collected USER-scope
    bullets too, the LOCAL chore was stamped due for pairs that do not exist in the LOCAL root, and
    the #131 refusal ledger (keyed on `(scope, root, [root/a, root/b])`) could never match those
    paths — the gate could not converge. When `scope` is given, only the bullets under that scope's
    OWN `## <SCOPE> scope` heading are collected. `scope=None` (test convenience / a caller that
    cannot name one) keeps the old scope-agnostic scan — degraded, but no worse than before.
    """
    out: list[tuple[str, str]] = []
    try:
        text = (root / "memory-reorg-proposed.md").read_text(encoding="utf-8")
    except OSError:
        return out
    in_section = False
    in_target_scope = scope is None
    for ln in text.splitlines():
        s = ln.strip()
        m_scope = _SCOPE_HEADING_RE.match(s)
        if m_scope:
            in_target_scope = scope is None or m_scope.group("scope") == scope
            in_section = False
            continue
        if s == _CONFLICT_SECTION_HEADING:
            in_section = True
            continue
        if in_section and s.startswith("#"):
            in_section = False
            continue
        if in_target_scope and in_section and s.startswith("- ") and s != _NO_CANDIDATES_SENTINEL:
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
    - ANY other `- ` bullet inside a Conflict-candidates section UNDER THIS SCOPE's OWN
      `## <SCOPE> scope` heading → True (dispatch; the agent still applies its own
      scope/legality judgment per pair).
    - file present but UNREADABLE → True (fail-open — not provably idle).

    Live evidence: a heartbeat conflict pass on 2026-07-08 abstained on the empty
    section at 260,931 tokens — the same no-op class as the other gates.

    SCOPE ATTRIBUTION (issue #162). `conflict_pairs` is scoped by `scope` — the librarian writes
    ONE combined proposal (one `### Conflict candidates` block per `## <SCOPE> scope` heading) into
    the LOCAL root, so an unscoped read of a LOCAL root previously collected USER/PROJECT bullets
    too, stamping the LOCAL chore due for pairs that do not live in the LOCAL root — and the #131
    ledger below could never converge it (its key names paths the LOCAL root does not contain).

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
    for a, b in conflict_pairs(root, scope):
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
    last_stats: dict[str, list[int]] | None = None,
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
        # `scope` is forwarded so the refusal filter can read the ledger (TRDD-9MQ25PNH);
        # when the caller has no scope the filter is skipped, never inverted. `max_bytes`
        # (the SAME split cap) also filters out structural pairs that could never legally
        # merge because their combined size already exceeds it (#210).
        return consolidate_has_work(
            root, last_stats=last_stats, stamp_age_s=stamp_age_s, scope=scope,
            max_bytes=split_max_bytes,
        )
    if intervention == "repair":
        # STRUCTURAL page-shape gate (semantic residual documented on the function).
        # `scope` also unlocks the per-page refusal filter, so a defect proven unfixable
        # stops out-ranking the fixable ones (#124).
        return repair_has_work(root, scope=scope)
    if intervention == "atomize":
        # Free-prose curated pages without atom markers (the skill's own candidate scan).
        # `scope` unlocks the per-page refusal filter (#212), so a page judged genuinely
        # un-atomizable (e.g. a boilerplate bootstrap stub) stops re-qualifying forever.
        return atomize_has_work(root, scope=scope)
    if intervention == "harvest":
        # Un-mirrored raw buffer notes (the skill's own step-1 scan). Needs the
        # scope to key the watermark ledger; scope unknown → fail-open.
        if scope is None:
            return True
        return harvest_has_work(scope, root)
    if intervention == "retro-lesson":
        # STRUCTURAL gate (TRDD-J3ZH3RSI): a superseded-status atom marker with no
        # superseded-by: pointer — the not-yet-converted signature. No such atom
        # anywhere → the retro pass can only abstain → suppress (PROVEN idle).
        return retro_lesson_has_work(root)
    if intervention == "conflict":
        # The pass consumes the librarian's surfaced candidates ("Empty/absent →
        # stop" is the skill's own precondition); discovery stays semantic and
        # stays the librarian's job. `scope` also unlocks the per-candidate refusal
        # filter — without it the gate keeps its old bullet-count behavior (#131).
        return conflict_has_work(root, scope=scope)
    # Unknown chores: fail-open by default.
    return True
