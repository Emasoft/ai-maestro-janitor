"""CLAUDE.md migration DELIVERY — the half that removes lines (TRDD-LFSWY0C6, CM-2 §4-5).

The DECISION half (`claudemd_migration_plan`) writes nothing, so running it on real input is
free. This module is the opposite: it is the only code on this card that can DESTROY
knowledge, and the card's §5 names that risk first — *"the chore removes lines it failed to
write anywhere"*. So the shape here is a chain of REFUSALS with a removal at the end, not a
removal with some checks bolted on.

**The order is load-bearing.** `apply_migration` is PURE: it takes the current CLAUDE.md
text and returns a CANDIDATE text, so every gate runs BEFORE anything reaches disk. The
existing `claudemd_slim verify --old` compares the on-disk file against a pre-migration copy
— i.e. it can only speak AFTER the removal already happened. For an unattended chore that is
the wrong order: "we deleted it, then checked" leaves a window where the only thing standing
between the user and lost narrative is a backup nobody is watching. Here a failed gate means
the write never occurs.

**Preservation and correctness are different properties, and the oracle only checks the
first.** That sentence is this card's most expensive lesson (see its 2026-08-13 STATE
entries): the preservation oracle proves the text landed SOMEWHERE, never that it was right
to remove it from CLAUDE.md. A run that folded the project's own description into a wiki page
would satisfy the oracle completely and still leave a CLAUDE.md that violates §CM-1, which
REQUIRES a description. That is why `_gate_only_excess_blocks` exists and why it runs before
the oracle rather than trusting it — it is the guard for the failure the oracle is blind to.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import claudemd_migration_plan as cmig
import memory_edit_verify as mev
from repomap.claudemd_slim import (
    MAP_FENCE_END,
    MAP_FENCE_START,
    WIKIMEM_FENCE_END,
    WIKIMEM_FENCE_START,
    narrative_outside_fences,
)
from repomap.markers import _fence_span

# Refusal reason slugs — stable, greppable identities for each gate. A caller (or a test)
# asserts on these, never on the human sentence, so the wording can improve without
# breaking the contract.
REFUSE_NOTHING_REQUESTED = "nothing-requested"
REFUSE_NOT_EXCESS = "not-excess"
REFUSE_NOT_UNIQUE = "not-uniquely-located"
REFUSE_FENCE_ALTERED = "fence-altered"
REFUSE_URL_DROPPED = "github-url-dropped"
REFUSE_CONTENT_DROPPED = "content-dropped"


@dataclass(frozen=True)
class Refusal:
    """One gate saying no. `reason` is a slug above; `detail` is for the human."""

    reason: str
    detail: str


@dataclass(frozen=True)
class ApplyResult:
    """The verdict for one apply. `text` is meaningful ONLY when `refusals` is empty —
    there is no partial success, because a partly-applied migration is a CLAUDE.md the
    next run cannot reason about."""

    text: str = ""
    refusals: list[Refusal] = field(default_factory=list)
    removed: int = 0

    @property
    def ok(self) -> bool:
        return not self.refusals


def _fence_text(text: str, start: str, end: str) -> str:
    """The fenced region VERBATIM (empty when the fence is absent) — the byte-comparison
    subject for `_gate_fences_untouched`."""
    span = _fence_span(text, start, end)
    return "" if span is None else text[span[0] : span[1]]


def _gate_only_excess_blocks(claude_md_text: str, block_texts: list[str]) -> list[Refusal]:
    """Every requested removal must be a block the PLANNER's own classifier called excess.

    Two distinct failure modes, one rule — and the rule is `classify_blocks`, the same call
    the planner selects on, never a reimplementation of it:

    - a PERMITTED element (the description, a project-URL line, a dev-ops command) is
      requested. §CM-1 requires those to stay, so removing one is wrong even when the
      preservation oracle is perfectly happy — which it would be, since the text did land in
      a wiki page. The oracle cannot see this class at all.
    - text that is not a narrative block of this file at all — a caller's paraphrase, a
      stale block from an earlier read, or a line that lives inside a janitor fence. Matching
      such a string against the raw file is how a delete lands somewhere nobody intended.
    """
    classified = cmig.classify_blocks(claude_md_text)
    excess = {block.text for block, element in classified if element is None}
    permitted = {block.text: element for block, element in classified if element is not None}
    refusals: list[Refusal] = []
    for requested in block_texts:
        if requested in excess:
            continue
        element = permitted.get(requested)
        if element is not None:
            refusals.append(
                Refusal(
                    REFUSE_NOT_EXCESS,
                    f"refusing to remove a §CM-1 PERMITTED element ({element}): {requested[:120]!r}",
                )
            )
        else:
            refusals.append(
                Refusal(
                    REFUSE_NOT_EXCESS,
                    f"not a narrative block of this CLAUDE.md: {requested[:120]!r}",
                )
            )
    return refusals


def _remove_unique(text: str, block_text: str) -> tuple[str, Refusal | None]:
    """Delete the ONE occurrence of `block_text`, or refuse.

    Exact-unique-match is the Edit tool's discipline and it is here for the same reason: a
    regex or a first-match delete cannot tell the intended line from a coincidental twin, and
    the failure is silent. Zero occurrences is equally a refusal — it means the block came
    from a different revision of the file (or straddles a fence, so its joined narrative text
    never existed contiguously), and guessing at that point is the whole hazard.
    """
    count = text.count(block_text)
    if count != 1:
        return text, Refusal(
            REFUSE_NOT_UNIQUE,
            f"block occurs {count} time(s) in CLAUDE.md, need exactly 1: {block_text[:120]!r}",
        )
    head, _, tail = text.partition(block_text)
    # Take the block's OWN line terminator with it, and nothing else — exact line removal.
    # This deliberately does NOT collapse the seam, so a paragraph that sat between blank
    # lines leaves BOTH behind (`A\n\nBLOCK\n\nB` -> `A\n\n\nB`, one extra blank line,
    # which markdown renders identically). Collapsing to a single blank would insert a gap
    # into a tight list — `- a\n- BLOCK\n- c` must stay `- a\n- c` — and would reflow text
    # the HUMAN wrote around a removal the janitor made, in a file they co-own. Measured
    # 2026-08-13: 60 removals on the real CLAUDE.md left exactly one 3-newline run, because
    # excess blocks are typically contiguous, so the accumulation is bounded and cosmetic.
    if head.endswith("\n") and tail.startswith("\n"):
        tail = tail[1:]
    return head + tail, None


def _gate_fences_untouched(before: str, after: str) -> list[Refusal]:
    """Both janitor fences must come through byte-identical (CM-2 step 5).

    Reachable despite the two gates above: a narrative block that STRADDLES a fence has its
    pre-fence and post-fence lines joined in the narrative, and if that joined string also
    happens to occur inside a fence, the uniqueness gate sees exactly one match — inside the
    fence. This is the check that catches the delete landing there.
    """
    refusals: list[Refusal] = []
    for label, start, end in (
        ("project-map", MAP_FENCE_START, MAP_FENCE_END),
        ("wikimem-index", WIKIMEM_FENCE_START, WIKIMEM_FENCE_END),
    ):
        if _fence_text(before, start, end) != _fence_text(after, start, end):
            refusals.append(Refusal(REFUSE_FENCE_ALTERED, f"the {label} fence would be altered by this removal"))
    return refusals


def _gate_github_url_survives(before_narrative: str, after_narrative: str) -> list[Refusal]:
    """A repo URL in the narrative is a slim-contract requirement (`slim_violations`), so a
    removal that strips the last one trades one violation for another. Only checked when the
    file HAD one — this gate repairs nothing, it just refuses to make things worse."""
    if "github.com/" in before_narrative and "github.com/" not in after_narrative:
        return [Refusal(REFUSE_URL_DROPPED, "removal would leave the narrative with no github repo url")]
    return []


def _gate_preservation(
    before_narrative: str, after_narrative: str, corpus_texts: list[str]
) -> list[Refusal]:
    """THE knowledge-shredding gate: every substantive fact line and every load-bearing
    token of the OLD narrative must survive into the NEW narrative or the wiki corpus.

    Same two oracles `claudemd_slim verify` uses (`memory_edit_verify`), applied to the
    CANDIDATE instead of the on-disk file — so a failure means the removal never happens,
    rather than being reported after the fact.
    """
    haystack = "\n".join([after_narrative, *corpus_texts])
    ok_facts, missing_facts = mev.body_facts_preserved([before_narrative], haystack)
    ok_tokens, missing_tokens = mev.fact_tokens_preserved([before_narrative], haystack)
    if ok_facts and ok_tokens:
        return []
    refusals = [Refusal(REFUSE_CONTENT_DROPPED, f"DROPPED fact line: {m[:160]}") for m in missing_facts]
    refusals += [Refusal(REFUSE_CONTENT_DROPPED, f"DROPPED token: {m[:160]}") for m in missing_tokens]
    return refusals


def apply_migration(
    claude_md_text: str, block_texts: list[str], corpus_texts: list[str]
) -> ApplyResult:
    """Remove `block_texts` from `claude_md_text` — or refuse, having changed nothing.

    PURE: `claude_md_text` and `corpus_texts` are read-only inputs and the result is a
    candidate string. Nothing here touches disk, so every gate is a pre-condition of the
    write rather than a post-mortem of it.

    `corpus_texts` is where the migrated knowledge is supposed to have landed — the caller
    (the memory agent) writes the atom or the fold FIRST, then asks to remove. Passing an
    empty corpus is the honest way to ask "would this removal lose anything?", and the answer
    for any real block is yes.

    Gates run cheapest-first, but the ordering that matters is `_gate_only_excess_blocks`
    ahead of `_gate_preservation`: correctness before preservation, because a permitted
    element that was dutifully copied into a wiki page passes the oracle and is still wrong.
    """
    if not block_texts:
        return ApplyResult(
            refusals=[Refusal(REFUSE_NOTHING_REQUESTED, "no blocks requested — nothing to migrate")]
        )

    refusals = _gate_only_excess_blocks(claude_md_text, block_texts)
    if refusals:
        return ApplyResult(refusals=refusals)

    candidate = claude_md_text
    for block_text in block_texts:
        candidate, refusal = _remove_unique(candidate, block_text)
        if refusal is not None:
            return ApplyResult(refusals=[refusal])

    refusals = _gate_fences_untouched(claude_md_text, candidate)
    if refusals:
        return ApplyResult(refusals=refusals)

    before_narrative = narrative_outside_fences(claude_md_text)
    after_narrative = narrative_outside_fences(candidate)
    refusals = _gate_github_url_survives(before_narrative, after_narrative)
    refusals += _gate_preservation(before_narrative, after_narrative, corpus_texts)
    if refusals:
        return ApplyResult(refusals=refusals)

    return ApplyResult(text=candidate, removed=len(block_texts))


def render_result(result: ApplyResult, *, dry_run: bool) -> str:
    """The CLI's human output. Pure, so a test asserts on it without a subprocess."""
    if result.ok:
        verb = "would remove" if dry_run else "removed"
        return (
            f"claudemd-migration-apply: {verb} {result.removed} block(s) — "
            "preservation PROVEN, both fences byte-identical\n"
        )
    lines = [f"claudemd-migration-apply: REFUSED ({len(result.refusals)} gate failure(s)) — CLAUDE.md untouched"]
    lines += [f"  [{r.reason}] {r.detail}" for r in result.refusals]
    return "\n".join(lines) + "\n"
