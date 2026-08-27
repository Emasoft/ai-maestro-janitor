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
import subprocess
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

# Same "unchanged corpus" reasoning as consolidate's gate 2 above, generalized (janitor#140)
# to every other precheckable chore whose real gate is per-page structural: split, repair,
# retro-lesson, atomize, conflict, harvest. Defined here (not beside `_unchanged_since_dispatch`
# below) because `split_has_work`'s default parameter value is evaluated at DEF time, before
# that helper is reached in file order.
_DEFAULT_RECHECK_S = _DEFAULT_CONSOLIDATE_RECHECK_S


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


_OVERSIZED_ATOM_RE = re.compile(r"^\S+\s+(?P<path>.+?):(?P<line>\d+)\s+\[atom-oversized\]")


def oversized_atom_pages(root: Path) -> list[tuple[str, int]]:
    """Pages under `root` carrying an over-budget atom, as `(abs-path, line)` — asked of
    `memgrep lint` itself rather than re-derived here (TRDD-VOWAUVE5, USER ruling 2026-08-22).

    WHY A SUBPROCESS AND NOT A PYTHON PREDICATE, in a module that is otherwise all Python
    predicates: the atom budget lives in Rust (`memory.rs::atom_max_chars`, env
    `MEMGREP_ATOM_MAX_CHARS`), and so does the atom SEGMENTATION that decides what "one
    atom's body" even is. A Python mirror of either is a second source of truth for a number
    and a parser — the exact drift class this file already names as a known hazard, and the
    one janitor#227 was: a gate and its arbiter disagreeing, so the chore dispatches an agent
    that finds nothing and re-dispatches forever. Asking the linter cannot drift from the
    linter. It costs ~40 ms for a whole scope root (measured on the live corpus), which is
    cheaper than the stat-and-read loops around it.

    NO CANDIDATES when memgrep is missing or fails, and that direction is deliberate — it is
    the opposite of this module's usual fail-OPEN. Everywhere else "unreadable" means "not
    provably idle, so dispatch"; here a dispatched agent would have no memgrep either, so it
    could neither find the candidates nor decompose them. Dispatching into that is a
    guaranteed no-op agent, which is the waste the whole precheck layer exists to prevent.
    A broken memgrep is a much louder problem than an undrained atom, and it surfaces
    elsewhere.
    """
    try:
        import user_mem_lib  # noqa: PLC0415 -- optional; a lib import must not break the gate

        binary = user_mem_lib.find_memgrep()
    except Exception:  # noqa: BLE001
        binary = None
    if not binary:
        return []
    try:
        proc = subprocess.run(  # noqa: S603 - resolved binary + one path, no shell
            [binary, "lint", str(root)],
            capture_output=True, text=True, timeout=60, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    out: list[tuple[str, int]] = []
    for ln in (proc.stdout or "").splitlines():
        m = _OVERSIZED_ATOM_RE.match(ln)
        if m:
            out.append((m.group("path"), int(m.group("line"))))
    return out


def split_has_work(
    root: Path,
    *,
    max_bytes: int,
    last_stats: dict[str, list[int]] | None = None,
    stamp_age_s: float | None = None,
    recheck_after_s: float = _DEFAULT_RECHECK_S,
) -> bool:
    """True iff some committed page in `root` is strictly larger than `max_bytes`
    (the split cap), OR some atom on any page is over the memgrep atom budget. Mirrors
    the split skill's `find -size +<cap>c` size gate with the SAME cap source
    (memory_settings split_max_bytes), and its `memgrep lint` atom scan with the same
    binary (see `oversized_atom_pages`).

    UNCHANGED-CORPUS gate (issue #140): if the corpus is byte-identical to the stat map
    recorded at the last split dispatch, and that dispatch is still within its recheck
    window, suppress — see `_unchanged_since_dispatch`. `last_stats`/`stamp_age_s` default
    to None (no stamp) which fails open (dispatch), matching every other caller here.

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
    if _unchanged_since_dispatch(
        root, last_stats=last_stats, stamp_age_s=stamp_age_s, recheck_after_s=recheck_after_s
    ):
        return False
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
    # An over-budget ATOM is the same trigger class as an over-cap PAGE — something is too
    # big and must be broken into smaller pieces of the same kind — so it rides this chore
    # rather than an eighth one. That is not just economy: memgrep's own refusal message
    # already names `janitor-memory-split` as the owner, and a NEW bare marker would be
    # unknown to any session running an older cached copy of the heartbeat-protocol rule,
    # so the fire would print a token nobody acts on. Checked LAST because it is the only
    # branch here that spawns a subprocess; the stat-only page scan short-circuits first.
    return bool(oversized_atom_pages(root))


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


def _unchanged_since_dispatch(
    root: Path,
    *,
    last_stats: dict[str, list[int]] | None,
    stamp_age_s: float | None,
    recheck_after_s: float,
) -> bool:
    """True iff the corpus under `root` is byte-identical to `last_stats` (the stat map
    recorded at this chore's LAST dispatch) AND that dispatch is still within its
    `recheck_after_s` recheck window — i.e. an agent already examined exactly this content
    and reached whatever verdict it reached, so re-spawning on the same bytes cannot yield a
    different answer (issue #140; generalizes consolidate's gate 2, TRDD-3XS3PDCF).

    Measured motivation: a peer's atomize chore abstained 10 consecutive times on a
    byte-identical corpus (~200k tokens each) before the corpus actually changed and the
    11th dispatch returned DONE — a dispatch whose candidate set is unchanged from the one
    that last abstained cannot produce a different answer.

    FAIL-OPEN (libs audit L-11): a missing stamp (`last_stats` empty or `stamp_age_s` is
    None), a stamp past its recheck window, or an unreadable corpus all return False — never
    suppress on uncertain input; only a PROVEN-unchanged, PROVEN-fresh stamp suppresses. The
    recheck-window escape hatch bounds the two cases an unchanged corpus could still hide
    real work: an agent that crashed before finishing, and LLM non-determinism (a pass one
    run would have acted on and another missed)."""
    if not last_stats or stamp_age_s is None or stamp_age_s >= recheck_after_s:
        return False
    current = page_stats(root)
    if current is None:
        return False  # unreadable corpus — not provably unchanged
    return not changed_pages(current, last_stats)


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


def _is_footer_heading(stripped: str) -> bool:
    """True iff this already-lstripped heading line names a footer section.

    `## See also` joined the family from the reporter's THIRD reproduction (a USER-scope
    page whose only footer was See also). The governing rule is "ANY trailing footer that
    precedes Notes", not "the link law's two sections" — the first fix covered three
    headings only because it was written from the issue body, whose examples happened to
    be `## Governed by` twice.
    """
    low = stripped.lower()
    heading_text = low.lstrip("#").strip()
    return (
        heading_text == "applies to"
        or heading_text == "governed by"
        or heading_text == "see also"
        or "notes and lessons learned" in low
        or "lessons learned" in low
    )


def _footer_heading_line(text: str) -> int | None:
    """0-based line index where the page's TRAILING footer region begins, or None.

    The footer is the maximal SUFFIX of the page made only of footer sections — `## Applies
    to`, `## Governed by`, `## See also`, or the Notes heading (any spelling
    `memory_edit_verify._LESSONS_HEADING` accepts). Fence-aware. Mirrors the memgrep crate's
    `footer_section_line` (janitor#250) so this precheck and `add-atom`'s insertion boundary
    can never disagree about where the footer starts — if they drift, one of them relocates
    atoms the other then flags as defects, forever.

    TRAILING, NOT EARLIEST (janitor#260). Both this and the Rust twin returned the FIRST
    footer-ish heading found scanning forward, which silently assumed footer headings only
    ever appear at the end of a page. They do not: `.claude/project/memory/
    janitor-architecture.md` carries `## See also` at line 279 of 524, with ordinary content
    sections and five atoms after it. Every one of those atoms was read as "inside the
    footer" and the page was flagged `atom-after-footer` forever.

    The cost was not cosmetic. `repair_has_work` gates the `[janitor-memory-repair]`
    dispatch, so 13 PROJECT pages looked permanently repairable; the dispatched agent then
    measured them with `memgrep lint`, found nothing, and declined — at ~250-300k tokens per
    no-op. That is janitor#260, and it is the SECOND occurrence of the shape the docstring
    above already warns about (janitor#227: this precheck and `memgrep lint` disagreeing, so
    the repair chore re-dispatched forever). The first fix made the two agree on WHICH
    headings are footers; they still disagreed with reality about WHERE the footer is.

    Note the old implementation contradicted its own stated rule — the docstring said "ANY
    TRAILING footer that precedes Notes" while the code took the earliest. The prose was
    right and the code was wrong, which is why the bug survived a reading.
    """
    lines = text.splitlines()
    # Fence state via the SHARED predicate in memory_edit_verify (this module's established SSOT
    # import), NOT a local startswith toggle. The naive rule read an inline ```span``` at line
    # start as an opener and swallowed every heading below it — and because the crate carried its
    # own copy of the same naive rule, the two agreed only by accident. janitor#227 and #260 were
    # both this precheck and `memgrep lint` disagreeing about page structure.
    fence: tuple[str, int] | None = None
    # (line index, is_footer) for every heading OUTSIDE a fence, in page order.
    headings: list[tuple[int, bool]] = []
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        fence, is_delim = memory_edit_verify.fence_step(line, fence)
        if is_delim:
            continue
        if fence is not None:
            continue
        if stripped.startswith("#"):
            headings.append((i, _is_footer_heading(stripped)))
    if not headings or not headings[-1][1]:
        # The page does not END in a footer section, so it has no trailing footer region.
        # A footer heading earlier in the page is an ordinary mid-page section (the
        # janitor-architecture.md case) and must not swallow everything after it.
        return None
    start = len(headings) - 1
    while start > 0 and headings[start - 1][1]:
        start -= 1
    return headings[start][0]


# REJECTED, and recorded so it is not re-attempted (janitor#260, tried 2026-08-14).
#
# The obvious next tightening is to break the trailing run when real content separates two
# footer headings — `## Governed by` → seven atoms → `## See also` → atoms → `## Notes`, which
# is the shape of the 34 pages this predicate still flags. It kills those flags. It is also
# CIRCULAR, and the suite proved it within seconds: the janitor#250 defect IS "an atom spliced
# into the trailing footer", so under a content-breaks-the-run rule the misplaced atom breaks
# the very run that would have flagged it. The defect makes itself invisible, and the two
# existing #250 regression tests went red.
#
# A rule that separates the two cases by DEGREE (one stray atom = defect, seven atoms + prose =
# a real section) is not a rule, it is a threshold waiting to be wrong.
#
# The residual 34 pages are pre-#250 `add-atom` fossils and are arguably genuinely misplaced;
# what makes them BURN is not this predicate's verdict but that the dispatched repair agent
# arbitrates with `memgrep lint`, which does not know this rule at all. Any predicate the
# arbiter does not share loops forever — janitor#227's shape, third occurrence. The fix is to
# move `atom-after-footer` INTO `memgrep lint` and have this precheck defer to it, so gate and
# arbiter cannot disagree. Tracked as the endgame on janitor#260.


# REJECTED, and recorded so it is not re-attempted (TRDD-AO8MPK5D, decided 2026-08-27).
#
# `memgrep lint` emits `publish-globally-missing` (29 PROJECT pages at the time of writing) and
# the repair skill's checklist used to claim that defect. This predicate has no check for it, so
# such a page is invisible to the gate AND absent from the candidate list. That looks like the
# janitor#227 parity hole, and the obvious fix is to widen the signature — `repair_defect(text,
# path=None)` or `(text, scope=None)` — and mirror memgrep's PROJECT test. Do not. Three reasons,
# each independently sufficient:
#
# 1. TEXT CANNOT DECIDE IT, EVEN WITH THE PATH. `publish_globally_state` (memory.rs:4878) reads
#    FILESYSTEM state — `has_symlink = symlink_resolves_to(user_root/<file>, page_abs)` — and
#    splits "field missing" into TWO issues on it: `MissingDefaultFalse` (no symlink → write
#    `false`) vs `MissingSymlinkImpliesTrue` (symlink present → write `true`). A predicate that
#    sees only text+path cannot tell those apart, so it would flag a page and hand the agent a
#    50/50 guess whose wrong branch silently UN-PUBLISHES a deliberately published page. Adding
#    it would buy the APPEARANCE of gate/arbiter parity for a rule family the gate structurally
#    cannot own — worse than the honest gap, because the next reader would stop looking.
#
# 2. THE DISAGREEMENT RUNS IN THE SAFE DIRECTION. janitor#227 loops because it is gate-LOUD and
#    arbiter-CLEAR: dispatch fires, the agent finds nothing, it re-dispatches forever. This one is
#    gate-SILENT and lint-loud, so it can never cause a dispatch and therefore can never loop or
#    burn a token. It is a coverage shortfall, not the #227 class. Do not reason about it as if
#    the two were the same bug wearing different hats.
#
# 3. IT SELF-HEALS, BY DESIGN. `atomic_write_page` (memory.rs:2526) is the SOLE choke point every
#    memgrep write verb funnels through, and it runs `normalize_page_until_clean` before AND after
#    every write, unconditionally (owner directive — no opt-in flag). The flagged pages are simply
#    pages nothing has written since the field was introduced; each fixes itself on its next write.
#
# And the shape that looks cleanest is the one that breaks a deliberate invariant: gating on a
# `scope=None` default would make this the FIRST None-path in this module that SUPPRESSES a real
# finding. `repair_has_work` (~:840) goes out of its way the other way — `if scope is None: return
# True  # cannot read the ledger ⇒ never suppress`. Fail-OPEN is the house posture; a scope-gated
# skip would be fail-CLOSED and would look identical to a clean corpus.
#
# EARLY SIGNAL THAT THIS DECISION WENT STALE: the `publish-globally-missing` count GROWING across
# releases rather than shrinking. That would mean pages are being written OUTSIDE the choke point
# (raw Edit-tool writes to PROJECT memory), which is a much bigger bug than the field itself.


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
    # Anchored to a HEADING LINE, never a raw substring (janitor#284). As `in text` these
    # asked "is this string anywhere on the page", so prose that merely QUOTED a heading
    # moved the verdict — and moved it both ways. The noisy way: a `component` page whose
    # lesson says "has `## Governed by` and no `## Applies to` — it is a component" was
    # flagged for correctly documenting that it is NOT mis-tiered, and was unfixable, since
    # the only way to clear the match is to reword a lesson the never-delete rule protects.
    # The dangerous way is the reason this is anchored rather than special-cased: the branch
    # below reads `not has_applies`, so ONE prose mention silently SUPPRESSES a genuinely
    # inverted aspect/hub — "the scope is clean" becomes indistinguishable from "the
    # detector was blinded". 20 pages across the six memory roots carry one of these strings
    # in prose only. Same class as janitor#255 (TRDD-DEAD-SYMBOL firing on words that were
    # never symbols): a predicate matching prose instead of structure.
    # NOT fence-aware, deliberately: measured 0 pages with either heading at column 0 inside
    # a fence, and the fence-aware walk in `_footer_heading_line` mirrors a Rust twin, so
    # reusing it here would couple this rule to that mirror for no measured gain.
    has_applies = re.search(r"^## Applies to", text, re.M) is not None
    has_governed = re.search(r"^## Governed by", text, re.M) is not None
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


def repair_has_work(
    root: Path,
    *,
    scope: str | None = None,
    now: int | None = None,
    last_stats: dict[str, list[int]] | None = None,
    stamp_age_s: float | None = None,
    recheck_after_s: float = _DEFAULT_RECHECK_S,
) -> bool:
    """True iff some candidate page in `root` is STRUCTURALLY malformed per the
    janitor-memory-repair checklist (TRDD-3XS3PDCF follow-up).

    UNCHANGED-CORPUS gate (issue #140): if the corpus is byte-identical to the stat map
    recorded at the last repair dispatch, and that dispatch is still within its recheck
    window, suppress before even reading a page — see `_unchanged_since_dispatch`. This is
    on top of, not instead of, the per-page REFUSAL FILTER below (which handles a page whose
    defect this pass provably cannot fix); the corpus gate additionally covers a defect that
    simply was not reached/fixed on the last dispatch, so an identical corpus need not be
    re-diagnosed until it moves or the recheck window elapses.

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
    if _unchanged_since_dispatch(
        root, last_stats=last_stats, stamp_age_s=stamp_age_s, recheck_after_s=recheck_after_s
    ):
        return False
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


def retro_lesson_has_work(
    root: Path,
    *,
    last_stats: dict[str, list[int]] | None = None,
    stamp_age_s: float | None = None,
    recheck_after_s: float = _DEFAULT_RECHECK_S,
) -> bool:
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
    buffer notes are never candidates (coexistence discriminator).

    UNCHANGED-CORPUS gate (issue #140): if the corpus is byte-identical to the stat map
    recorded at the last retro-lesson dispatch, and that dispatch is still within its
    recheck window, suppress — see `_unchanged_since_dispatch`. This chore has no per-page
    refusal ledger of its own, so this gate is its ONLY protection against re-dispatching
    on an atom the skill already converted/left alone last time."""
    if _unchanged_since_dispatch(
        root, last_stats=last_stats, stamp_age_s=stamp_age_s, recheck_after_s=recheck_after_s
    ):
        return False
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


def atomize_has_work(
    root: Path,
    *,
    scope: str | None = None,
    now: int | None = None,
    last_stats: dict[str, list[int]] | None = None,
    stamp_age_s: float | None = None,
    recheck_after_s: float = _DEFAULT_RECHECK_S,
) -> bool:
    """True iff some CURATED wiki page in `root` is an atomize candidate per
    `atomize_defect` (TRDD-3XS3PDCF follow-up). Unreadable pages fail OPEN.

    UNCHANGED-CORPUS gate (issue #140): if the corpus is byte-identical to the stat map
    recorded at the last atomize dispatch, and that dispatch is still within its recheck
    window, suppress before reading a single page — see `_unchanged_since_dispatch`. This is
    the fix for the measured incident that motivated this gate: a corpus unchanged since the
    last abstain cannot yield a different verdict on a re-spawn.

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
    if _unchanged_since_dispatch(
        root, last_stats=last_stats, stamp_age_s=stamp_age_s, recheck_after_s=recheck_after_s
    ):
        return False
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


def conflict_has_work(
    root: Path,
    *,
    scope: str | None = None,
    now: int | None = None,
    last_stats: dict[str, list[int]] | None = None,
    stamp_age_s: float | None = None,
    recheck_after_s: float = _DEFAULT_RECHECK_S,
) -> bool:
    """True iff the scope's `memory-reorg-proposed.md` carries at least one REAL
    conflict candidate (TRDD-3XS3PDCF follow-up — the last precheckable chore).

    UNCHANGED-CORPUS gate (issue #140): if the NOTE corpus is byte-identical to the stat
    map recorded at the last conflict dispatch, and that dispatch is still within its
    recheck window, suppress — see `_unchanged_since_dispatch`. Sound because conflict
    candidates are DERIVED from note content: the librarian re-lists the same pair on
    every run of an unchanged corpus (the exact noise the REFUSAL FILTER below already
    targets), and a genuinely new conflict can only appear when a note is added or edited
    — which moves the corpus fingerprint and re-arms this gate immediately.

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
    if _unchanged_since_dispatch(
        root, last_stats=last_stats, stamp_age_s=stamp_age_s, recheck_after_s=recheck_after_s
    ):
        return False
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


def harvest_has_work(
    scope: str,
    root: Path,
    *,
    last_stats: dict[str, list[int]] | None = None,
    stamp_age_s: float | None = None,
    recheck_after_s: float = _DEFAULT_RECHECK_S,
) -> bool:
    """True iff some RAW buffer note in `root` is not yet (or no longer) mirrored
    into the curated wiki (TRDD-3XS3PDCF follow-up — UNBLOCKED 2026-07-08 once the
    coexistence-mirror harvest model shipped in v0.33.0 and ran live).

    UNCHANGED-CORPUS gate (issue #140): if the corpus is byte-identical to the stat map
    recorded at the last harvest dispatch, and that dispatch is still within its recheck
    window, suppress before reading any note — see `_unchanged_since_dispatch`. Cheaper
    than the per-note watermark check below (a `stat`-only compare vs a full read + hash),
    and sound for the same reason: an unchanged corpus has no new/edited buffer note to
    mirror since the watermark was last updated.

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
    if _unchanged_since_dispatch(
        root, last_stats=last_stats, stamp_age_s=stamp_age_s, recheck_after_s=recheck_after_s
    ):
        return False
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


_ENRICH_SLUGS = frozenset({
    "atom-keywords-too-few",
    "atom-keywords-duplicated",
    "atom-no-keywords",  # the limiting case of too-few — same defect, same owner
    "page-description-too-few-phrases",
    "page-description-duplicated-phrases",
})

_ENRICH_FINDING_RE = re.compile(r"^\S+\s+(?P<path>.+?):(?P<line>\d+)\s+\[(?P<slug>[a-z-]+)\]")


def enrich_pages(root: Path) -> list[tuple[str, str]]:
    """Pages under `root` whose RECALL SURFACE is too thin or duplicated, as
    `(abs-path, slug)` — asked of `memgrep lint` itself, never re-derived here.

    Same reasoning as `oversized_atom_pages`, and for the same reason it must not be
    re-litigated per chore: the thresholds AND the parsing live in Rust
    (`memory.rs::atom-keywords-too-few` / `page-description-too-few-phrases`, with
    env-tunable minimums), and so does the normalization that decides when two
    keyphrases count as duplicates. A Python twin of a rule the linter already owns is
    not a second opinion, it is a second source of truth — the janitor#227 shape, where
    a gate and its arbiter disagree and the chore dispatches an agent that finds nothing,
    forever. Note this is the OPPOSITE of what janitor#227 is usually quoted for: the
    "lint and precheck disagree BY DESIGN" clause covers precheck-only rules lint does
    not know about. Here the defect IS a lint rule, so deferring to lint is the only
    non-looping design available.

    NO CANDIDATES when memgrep is missing or fails — fail CLOSED, deliberately, exactly
    as `oversized_atom_pages` does: a dispatched agent would have no linter either, so it
    could neither confirm the defect nor verify its own fix.

    ⚠ THE BINARY MUST BE ONE THAT KNOWS THESE RULES. They shipped after the currently
    installed build, so during the backlog drain (TRDD-437UHNFS) `find_memgrep()` resolves
    PATH to a binary containing ZERO of these slugs and this function correctly returns []
    for every page. That is not a bug here and must not be "fixed" by counting in Python —
    it is why the 1188-error backlog is drained by an EAGER batch run with
    `MEMGREP_BIN=<repo>/scripts/memgrep/target/release/memgrep`, and why this chore is the
    POST-install steady-state guard rather than the thing that drains.
    """
    try:
        import user_mem_lib  # noqa: PLC0415 -- optional; a lib import must not break the gate

        binary = user_mem_lib.find_memgrep()
    except Exception:  # noqa: BLE001
        binary = None
    if not binary:
        return []
    try:
        proc = subprocess.run(  # noqa: S603 - resolved binary + one path, no shell
            [binary, "lint", str(root)],
            capture_output=True, text=True, timeout=60, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    out: list[tuple[str, str]] = []
    for ln in (proc.stdout or "").splitlines():
        m = _ENRICH_FINDING_RE.match(ln)
        if m and m.group("slug") in _ENRICH_SLUGS:
            out.append((m.group("path"), m.group("slug")))
    return out


def enrich_has_work(
    root: Path,
    *,
    scope: str | None = None,
    now: int | None = None,
    last_stats: dict[str, list[int]] | None = None,
    stamp_age_s: float | None = None,
    recheck_after_s: float = _DEFAULT_RECHECK_S,
) -> bool:
    """True iff some page in `root` has a thin or duplicated recall surface that the
    enrich pass could still fix (TRDD-437UHNFS).

    TERMINATION, which is the whole design question for this chore: the gate and the
    arbiter are THE SAME CODE — both are `memgrep lint`. So a page the agent actually
    fixed cannot re-flag on the next pass, and a page it cannot satisfy goes on the
    refusal ledger and stops being a candidate until its own bytes change. Those are the
    only two exits, and both are monotone; there is no third state in which this loops.

    NON-INTERFERENCE with the other chores: the enrich pass writes ONLY `keywords:` props
    and the page-level `description:`. It must never touch an atom's `desc:` — that field
    has a 200-char cap enforced elsewhere (`memory_edit_verify.py`), so padding it would
    hand `repair` a defect to undo and the two chores would ping-pong on the same page.

    UNCHANGED-CORPUS gate (#140) is the cheap fast path, as everywhere else. `scope` is
    required to read the refusal ledger; without it the filter is skipped, never inverted.
    """
    if _unchanged_since_dispatch(
        root, last_stats=last_stats, stamp_age_s=stamp_age_s, recheck_after_s=recheck_after_s
    ):
        return False
    for path, _slug in enrich_pages(root):
        if scope is None:
            return True  # cannot read the ledger ⇒ never suppress
        if not memory_refusals.is_refused("enrich", scope, root, [Path(path)], now=now):
            return True
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
    can't read it, so we never suppress), and for every intervention when the caller
    supplied no dispatch stamp (`last_stats`/`stamp_age_s` default to None). A chore is
    suppressed ONLY when its idleness is cheaply PROVEN; otherwise the scheduler keeps
    its existing cadence-only behavior.

    UNCHANGED-CORPUS gate (issue #140): EVERY intervention below is forwarded
    `last_stats`/`stamp_age_s` — a corpus byte-identical to the one already examined at
    the chore's last dispatch, within its recheck window, is provably idle (see
    `_unchanged_since_dispatch`). Originally only CONSOLIDATE carried this gate; a
    peer's atomize chore was measured abstaining 10 consecutive times on an unchanged
    corpus before it moved on the 11th, so the gate is now generalized to every
    precheckable chore rather than duplicated ad hoc per caller."""
    if intervention == "split":
        if split_max_bytes <= 0:
            return True  # cap unreadable/disabled → fail-open (do not suppress)
        return split_has_work(
            root, max_bytes=split_max_bytes, last_stats=last_stats, stamp_age_s=stamp_age_s,
        )
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
        # stops out-ranking the fixable ones (#124). UNCHANGED-CORPUS gate (#140) is the
        # additional, cheaper fast path.
        return repair_has_work(
            root, scope=scope, last_stats=last_stats, stamp_age_s=stamp_age_s,
        )
    if intervention == "atomize":
        # Free-prose curated pages without atom markers (the skill's own candidate scan).
        # `scope` unlocks the per-page refusal filter (#212), so a page judged genuinely
        # un-atomizable (e.g. a boilerplate bootstrap stub) stops re-qualifying forever.
        # UNCHANGED-CORPUS gate (#140) is the additional, cheaper fast path.
        return atomize_has_work(
            root, scope=scope, last_stats=last_stats, stamp_age_s=stamp_age_s,
        )
    if intervention == "harvest":
        # Un-mirrored raw buffer notes (the skill's own step-1 scan). Needs the
        # scope to key the watermark ledger; scope unknown → fail-open. UNCHANGED-CORPUS
        # gate (#140) is the additional, cheaper fast path.
        if scope is None:
            return True
        return harvest_has_work(
            scope, root, last_stats=last_stats, stamp_age_s=stamp_age_s,
        )
    if intervention == "retro-lesson":
        # STRUCTURAL gate (TRDD-J3ZH3RSI): a superseded-status atom marker with no
        # superseded-by: pointer — the not-yet-converted signature. No such atom
        # anywhere → the retro pass can only abstain → suppress (PROVEN idle).
        # UNCHANGED-CORPUS gate (#140) is this chore's ONLY refusal-ledger-free fast path.
        return retro_lesson_has_work(root, last_stats=last_stats, stamp_age_s=stamp_age_s)
    if intervention == "conflict":
        # The pass consumes the librarian's surfaced candidates ("Empty/absent →
        # stop" is the skill's own precondition); discovery stays semantic and
        # stays the librarian's job. `scope` also unlocks the per-candidate refusal
        # filter — without it the gate keeps its old bullet-count behavior (#131).
        # UNCHANGED-CORPUS gate (#140) is the additional, cheaper fast path.
        return conflict_has_work(
            root, scope=scope, last_stats=last_stats, stamp_age_s=stamp_age_s,
        )
    if intervention == "enrich":
        # LINT-OWNED gate (TRDD-437UHNFS): thin/duplicated keyphrases and page
        # descriptions are rules memgrep already owns, so the gate ASKS it rather than
        # counting here — gate and arbiter identical, which is what makes the chore
        # terminate. `scope` unlocks the per-page refusal filter for a page that cannot
        # be honestly enriched (a stub with genuinely one subject). Fails CLOSED when
        # memgrep is missing, unlike the fail-OPEN default around it — an agent without
        # the linter could not verify its own fix either.
        return enrich_has_work(
            root, scope=scope, last_stats=last_stats, stamp_age_s=stamp_age_s,
        )
    # Unknown chores: fail-open by default.
    return True
