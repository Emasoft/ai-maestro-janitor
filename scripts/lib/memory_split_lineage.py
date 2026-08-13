"""Split lineage — the marker meaning "the janitor itself separated these two pages" (TRDD-3QIQ2E6J).

A split takes one oversized page and emits an overview plus N sub-pages. Those siblings share
vocabulary BY CONSTRUCTION — the split is what gave them a common subject — so the librarian's
conflict scan surfaces them, an agent is dispatched, it declines, and the next split-shaped edit
re-arms the whole cycle. Measured cost of one such round on a 62 KB corpus: **221,612 subagent
tokens for ZERO mutations** (janitor#241).

The refusal ledger cannot fix this, and that is the load-bearing point. `memory_refusals`
keys a candidate on its root-relative PATHS and validates it with a hash of the pages' BYTES —
a split changes both by construction, so every recorded refusal stops matching the moment the
split lands. Carrying the parent's refusals onto the children would be worse than the
re-litigation: after a split the pair genuinely IS different (different names, different bytes,
different subjects), so a refusal claiming to have judged "these two" would assert a verdict
nobody reached. A ledger that lies is a worse failure than a chore that repeats.

So the fix is upstream of refusals: split siblings must never become conflict CANDIDATES.

WHY AN EXPLICIT MARKER, AND NOT THE CHEAPER DERIVATION
------------------------------------------------------
`verify_split` already requires a split to emit an overview that links every sub-page, so
"siblings = both linked from one overview" looked free — no schema change at all. It fails the
card's acceptance box 2 ("a genuine conflict between UNRELATED pages still fires"): a hub links
ALL its components, not only the pages one split produced, so that predicate silences genuine
conflicts BETWEEN two components of the same hub. Link-derived sibling-hood is strictly WIDER
than split-sibling-hood, and over-suppression is invisible by construction — the chore simply
goes quiet and nobody can tell whether it was right. Do not revive it. Prefix-derived ancestry
(shared filename stem) fails identically and for the same reason.

An ID, NOT THE PARENT'S NAME: the question this answers is "did ONE split event produce both of
these?", and an id answers it directly. Naming the parent breaks the moment the parent is renamed
or itself split again. The id used is the split transaction's own `txn_id`, which is already
minted, already unique, and traceable back to that transaction's journal — so the audit trail
costs nothing extra.

RE-SPLIT OVERWRITES, DELIBERATELY. If a child is later split again, its grandchildren carry the
NEWER id. That is correct: they are siblings of the second event, and the pages from the first
event are no longer siblings of anything the second event produced.

COEXISTENCE WITH THE `publish-globally` NORMALIZER — verified, not assumed. That normalizer
(memgrep `atomic_write_page`, commits 9ddb3cf7 / 25013e64) brackets every memgrep page write with
a fixed-point loop, and the card warned the two writers could fight: "one inserting a field the
other does not know about, each rewriting the page the other just fixed, every write, forever."
They cannot, and the reason is specific: its only content mutation is
`insert_frontmatter_field(text, "publish-globally", ...)`, which splices ONE line in before the
closing `---` and copies every other line through verbatim (`memory.rs:4260`). An unknown
frontmatter key is preserved, so `split-lineage:` survives the normalizer untouched and the loop
still converges. The split path is Python (`memory_txn`) and never invokes the Rust writer at
all, which is also why this needs no Rust change and no memgrep release.
"""

from __future__ import annotations

import re

#: The frontmatter key. One word, hyphenated like every other wikimem field, and greppable —
#: `grep -rn 'split-lineage:'` over a corpus answers "which pages came from a split?" with no
#: tooling at all.
FIELD = "split-lineage"

#: A lineage id is the transaction's `uuid4().hex`. Validated on BOTH sides rather than trusted:
#: the value is read back out of a file any agent may have hand-edited, and a malformed value must
#: mean "no lineage" (⇒ the pair is still judged) rather than silently matching another malformed
#: value. Two pages whose lineage is `""` are NOT siblings — see `same_split`.
_ID_RE = re.compile(r"\A[0-9a-f]{32}\Z")

#: Only a TOP-LEVEL key counts: `split-lineage:` at column 0 inside the leading `---` block. An
#: indented occurrence is a value nested under some other key, and a line inside the BODY is prose
#: (a page documenting this very mechanism would otherwise appear to carry a lineage — this module's
#: own tests include exactly that case).
_FIELD_RE = re.compile(rf"\A{re.escape(FIELD)}:\s*(?P<value>.*?)\s*\Z")


def _frontmatter_bounds(text: str) -> tuple[int, int] | None:
    """`(first_body_index, close_index)` of the leading `---`…`---` block, or None when absent.

    A page with no leading `---`, or one whose block is opened and never closed, has no
    frontmatter this module will touch — inserting a key into a malformed block would corrupt it,
    and the wikimem linter already reports that defect under its own finding.
    """
    lines = text.split("\n")
    if not lines or lines[0].rstrip() != "---":
        return None
    for i in range(1, len(lines)):
        stripped = lines[i].rstrip()
        if stripped in ("---", "..."):
            return 1, i
    return None


def lineage_of(text: str) -> str:
    """The page's split-lineage id, or `""` when it declares none (or declares a malformed one).

    Pure. A malformed value is reported as absent rather than returned, so a corrupt field can
    never make two unrelated pages compare equal.
    """
    bounds = _frontmatter_bounds(text)
    if bounds is None:
        return ""
    first, close = bounds
    lines = text.split("\n")
    for line in lines[first:close]:
        m = _FIELD_RE.match(line)
        if m is None:
            continue
        value = m.group("value")
        return value if _ID_RE.match(value) else ""
    return ""


def same_split(text_a: str, text_b: str) -> bool:
    """True iff both pages carry the SAME valid split-lineage id — i.e. one split emitted both.

    Pure, and deliberately strict: an empty id on either side is False. "Neither page has a
    lineage" must never read as "these are siblings", or every page in a corpus with no splits
    would suppress against every other — the widest possible over-suppression, from the narrowest
    possible bug.
    """
    a = lineage_of(text_a)
    return bool(a) and a == lineage_of(text_b)


def stamp(text: str, split_id: str) -> str:
    """Return `text` carrying `split-lineage: <split_id>`, replacing any id already there.

    Pure. Returns the text UNCHANGED when `split_id` is malformed or the page has no well-formed
    frontmatter — a stamp is an optimization for a later scan, never a reason to damage a page or
    to write a value the reader would reject anyway.

    Replacing rather than appending is what makes a re-split correct (see the module docstring),
    and it is also what keeps this idempotent: stamping the same page with the same id twice is a
    no-op, so a re-staged write does not accumulate duplicate keys.
    """
    if not _ID_RE.match(split_id):
        return text
    bounds = _frontmatter_bounds(text)
    if bounds is None:
        return text
    first, close = bounds
    lines = text.split("\n")
    new_line = f"{FIELD}: {split_id}"
    for i in range(first, close):
        if _FIELD_RE.match(lines[i]):
            if lines[i] == new_line:
                return text
            lines[i] = new_line
            return "\n".join(lines)
    # Insert immediately BEFORE the closing delimiter, exactly where the `publish-globally`
    # normalizer puts its own field — so the two writers produce the same shape and a page
    # touched by both has no tell-tale ordering difference to diff against.
    lines.insert(close, new_line)
    return "\n".join(lines)


def is_split_child(rel_path: str, *, sources: object, exists_in_live: bool) -> bool:
    """Is this staged write one of the pages the split PRODUCED (⇒ stamp it)?

    Pure; `sources` is any container supporting `in` (the transaction's source map).

    A split transaction writes three kinds of page and only two of them are children:

      * a **NEW** path (nothing at that path in the live tree) — a sub-page the split created.
      * the **SOURCE** path itself — the oversized page, rewritten in place as the overview.
      * a pre-existing page that is NOT a source — a BACKLINK REDIRECT, where
        `canonicalize_retired_links` repointed some other page's `[[links]]` at the survivor.

    That third kind is why this predicate exists at all. Stamping it would mark an unrelated page
    as a sibling of the split's children and silence genuine conflicts against it — precisely the
    over-suppression acceptance box 2 protects, arriving through the back door of a helpful-looking
    "stamp everything this transaction wrote".
    """
    if rel_path in sources:  # type: ignore[operator]
        return True
    return not exists_in_live
