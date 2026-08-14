#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""trdd-cross-card-blindspot — flag OPEN cards attacking one defect blind to each other.

The gap this closes (TRDD-XFPOAF2I): none of the existing TRDD detectors
(trdd-drift, trdd-reminder, trdd-state-reconciliation, report-to-trdd-drift)
compare two cards AGAINST EACH OTHER — every one of them judges a card against
the tree. TRDD-RG4IUZ6I and TRDD-3QIQ2E6J were filed 4 days apart for the SAME
defect (janitor#241), quoting the same measurement, and neither referenced the
other — they agreed on half the fix and prescribed OPPOSITE things on the
other half. It surfaced only because two titles happened to be read back to
back on a 113-card board — luck, not process.

Two independent signals, run and reported together:

1. **Shared `external-refs:`** — a PAIR of OPEN cards sharing an
   `external-refs:` entry that do NOT reference each other (in either card's
   `external-refs:` or body). Sharing a ref is NOT a contradiction — a parent
   and its derived task, a detector and its fix, legitimately cite the same
   issue — so this NEVER asserts the two cards disagree. It says only "these
   two may not know about each other"; cross-referencing (once either side
   names the other) is the correct silencer.
2. **Shared rare vocabulary in title + STATE block** (TRDD-4EKZ81MV — closes
   the blind spot signal (1) structurally cannot see: two cards that never
   shared a ref at all). Two OPEN, non-cross-referenced cards whose title +
   `## STATE` block (or, absent a STATE block, the whole body) share at
   least `_MIN_SHARED_CONTENT_WORDS` words that are BOTH long enough to be
   specific (`_MIN_WORD_LEN`) AND rare across the current board (appear on
   at most `_rarity_threshold()` open cards). The rarity gate is what keeps
   this sound: a word every card uses ("janitor", "detector", "board") has
   high document frequency and is excluded regardless of length, so common
   house vocabulary cannot manufacture a pair — only genuinely distinctive,
   shared terms (e.g. "symlink" + "mechanism", or "iTerm" + "automation")
   can. Requiring 2+ such words (not 1) additionally guards against a single
   coincidental rare-word match between two unrelated cards.

SURFACE-ONLY: this detector mutates ZERO TRDD files, ever. Zero model tokens
— both signals are pure string/set operations over already-parsed frontmatter
and body text. Terminal and archived/refused cards are excluded (a closed
card cannot be re-litigated and the archived/refused folders are not scanned
at all).

Slow-moving board hygiene — daily cadence; per-(signal, key, pair) seen-file
dedupe.
"""

from __future__ import annotations

import itertools
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import state  # noqa: E402
import trdd_common  # noqa: E402

# `external-refs:` is a flow-style list, same grammar as `blocked-by:` /
# `implementation-commits:` — no dedicated regex exists in trdd_common yet, so
# this detector carries its own, anchored the same way FM_BLOCKED_BY_RE etc.
# are (within the matched frontmatter block, MULTILINE).
_FM_EXTERNAL_REFS_RE = re.compile(r"^external-refs:[ \t]*(.+)$", re.MULTILINE)

# Cap how many pairs we name inline in the single drift line — the rest are
# just counted. Keeps the heartbeat line short on a board with many hits.
_MAX_LISTED = 8

_FM_TITLE_RE = re.compile(r"^title:[ \t]*(.+)$", re.MULTILINE)


@dataclass
class _Card:
    """Everything this detector needs from ONE open TRDD card."""

    uid: str
    scope: str
    ext_refs: list[str] = field(default_factory=list)  # raw external-refs elements
    body: str = ""
    title: str = ""


def _normalize_ref(ref: str) -> str:
    """Fold a ref element to a stable grouping key — case/whitespace only.

    Cards write refs like `janitor#241` or `TRDD-RG4IUZ6I` consistently in
    practice; this is deliberately NOT a fuzzy matcher (no attempt to treat
    `janitor#241` and `#241` as the same thing) — an exact-modulo-case match
    keeps the detector predictable and avoids inventing false pairings.
    """
    return ref.strip().lower()


_BARE_OR_PREFIXED_TRDD_RE = re.compile(r"\A(?:trdd-)?([0-9a-z]{8})\Z", re.IGNORECASE)


def _mentions_uid(elements: list[str], target_uid: str) -> bool:
    """True iff some element of `elements` names `target_uid` (bare or TRDD-prefixed)."""
    t = target_uid.upper()
    for el in elements:
        m = _BARE_OR_PREFIXED_TRDD_RE.match(el.strip())
        if m and m.group(1).upper() == t:
            return True
    return False


def _references(card: _Card, target_uid: str) -> bool:
    """True iff `card` already names `target_uid` — the cross-reference silencer.

    Checked in both places the spec names: the card's own `external-refs:`
    (bare id8 or `TRDD-<id8>`), and anywhere in the card's body (a STATE
    block, a prose mention, a `blocked-by:`-style citation).
    """
    if _mentions_uid(card.ext_refs, target_uid):
        return True
    t = target_uid.upper()
    return any(uid.upper() == t for uid in trdd_common.extract_trdd_refs(card.body))


# ── Signal 2: shared rare vocabulary (TRDD-4EKZ81MV) ──────────────────────
#
# Two cards that never shared an `external-refs:` value are structurally
# invisible to signal 1 (see the module docstring). This signal keys on
# distinctive shared WORDS in the title + STATE block instead of a shared
# citation, so it fires on exactly the cases signal 1 cannot: a card with
# NO external-refs at all, or two cards that named different issue numbers
# for the same underlying defect.

_MIN_WORD_LEN = 5  # below this, words are too generic to be specific evidence
_MIN_SHARED_CONTENT_WORDS = 2  # a single coincidental rare word is not enough
_RARITY_ABS_FLOOR = 2  # always allow a word seen on up to this many cards
_RARITY_FRACTION = 0.03  # ...or this fraction of the open board, whichever is larger

_WORD_RE = re.compile(r"[a-z][a-z0-9']*")

# Generic English/house-vocabulary glue words that would otherwise slip past
# the rarity gate on a SMALL board (few cards -> everything looks "rare" by
# document-frequency alone). On the real, large board the rarity gate above
# does most of the work; this list exists so the signal stays sound even on
# a 2-3 card fixture where df-based rarity has no discriminating power yet.
_CONTENT_STOPWORDS: frozenset[str] = frozenset(
    {
        "about", "above", "after", "again", "against", "all", "also", "although",
        "always", "among", "another", "anyone", "anything", "around", "because",
        "before", "being", "below", "between", "board", "body", "bugfix", "cannot",
        "card", "cards", "change", "changed", "changes", "close", "closed", "column",
        "could", "detector", "detectors", "does", "doing", "down", "during", "each",
        "either", "even", "every", "external", "false", "field", "file", "files",
        "first", "found", "from", "given", "have", "having", "here", "however",
        "instead", "into", "issue", "issues", "itself", "janitor", "just", "later",
        "least", "logic", "maybe", "might", "more", "most", "much", "must", "never",
        "next", "notes", "occur", "often", "once", "only", "open", "other", "over",
        "owned", "owner", "pairs", "parse", "project", "quite", "ratio", "reads",
        "ready", "refer", "refs", "scope", "session", "shall", "share", "shared",
        "should", "signal", "since", "some", "state", "still", "such", "task",
        "tasks", "test", "tests", "than", "that", "their", "them", "then", "there",
        "these", "they", "this", "those", "though", "through", "title", "todo",
        "trdd", "trdds", "true", "under", "until", "using", "value",
        "very", "were", "what", "when", "where", "which", "while", "will", "with",
        "within", "without", "would", "write", "wrote",
    }
)


def _content_words(text: str) -> set[str]:
    """Tokenize `text` into the SIGNIFICANT-word set used for the similarity gate.

    Lowercased, `_MIN_WORD_LEN`+ chars, stopwords stripped. Deliberately not
    stemmed/lemmatized — a false negative (missed plural/tense match) is
    cheap here, a false positive from over-eager normalization is not.
    """
    words: set[str] = set()
    for tok in _WORD_RE.findall(text.lower()):
        if len(tok) < _MIN_WORD_LEN or tok in _CONTENT_STOPWORDS:
            continue
        words.add(tok)
    return words


def _similarity_text(card: _Card) -> str:
    """The text signal 2 compares: title + STATE block, falling back to the
    whole body when no `## STATE` heading exists (design-prose-only cards —
    the iTerm trio is mostly this shape, per the card's evidence)."""
    state_block = trdd_common.extract_state_block(card.body)
    return card.title + "\n" + (state_block if state_block else card.body)


def _rarity_threshold(total_cards: int) -> int:
    """A word counts as "rare" iff it appears on at most this many open cards.

    `_RARITY_ABS_FLOOR` keeps small boards usable (df-based rarity alone has
    no power below a few dozen cards); `_RARITY_FRACTION` is what makes the
    gate SCALE — on a 274-card board a word appearing on 3% of cards (≈8)
    is still common house vocabulary, not a specific shared term.
    """
    return max(_RARITY_ABS_FLOOR, int(total_cards * _RARITY_FRACTION))


def _find_content_similarity_pairs(
    cards: dict[str, _Card],
) -> dict[frozenset[str], set[str]]:
    """Return {frozenset({uid_a, uid_b}): shared_rare_words} for every pair whose
    shared rare-word count meets `_MIN_SHARED_CONTENT_WORDS`. Cross-referenced
    pairs are NOT filtered here — the caller applies the same `_references`
    silencer signal 1 uses, so both signals share one cross-link escape hatch.
    """
    card_words: dict[str, set[str]] = {
        uid: _content_words(_similarity_text(card)) for uid, card in cards.items()
    }
    df: Counter[str] = Counter()
    for words in card_words.values():
        df.update(words)
    threshold = _rarity_threshold(len(cards))
    rare_words = {w for w, c in df.items() if c <= threshold}

    # Inverted index restricted to rare words only — on a large board this
    # keeps the pairing work proportional to how many cards share a
    # DISTINCTIVE term, never O(cards^2) over the whole corpus.
    word_to_uids: dict[str, list[str]] = {}
    for uid, words in card_words.items():
        for w in words & rare_words:
            word_to_uids.setdefault(w, []).append(uid)

    pair_shared: dict[frozenset[str], set[str]] = {}
    for word, uids in word_to_uids.items():
        if len(uids) < 2:
            continue
        for a, b in itertools.combinations(sorted(uids), 2):
            pair_shared.setdefault(frozenset({a, b}), set()).add(word)

    return {
        pair: words
        for pair, words in pair_shared.items()
        if len(words) >= _MIN_SHARED_CONTENT_WORDS
    }


def _parse_card(path: Path, scope: str) -> _Card | None:
    """Parse one TRDD file into a `_Card`, or None when it has no usable id."""
    uid = trdd_common.extract_uid(path.name)
    if uid is None:
        return None
    # WHOLE FILE, not `RECONCILE_BYTES`. The body is what the cross-reference SILENCER
    # (`_references`) searches, so a truncated read makes a citation past the cap invisible and
    # the pair is re-reported forever — cross-linking, the remedy this detector recommends,
    # cannot silence it. Measured on this board: 11 of 274 cards exceed the 24 KB cap, and the
    # longest cards are precisely the most cross-referenced ones. The frontmatter parse below
    # is unaffected (it is anchored at the top of the file either way).
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    fm = trdd_common.FRONTMATTER_RE.match(text)
    if not fm:
        return None
    _, column = trdd_common.parse_state_text(text)
    if trdd_common.is_terminal_column(column):
        return None
    ext_refs: list[str] = []
    rm = _FM_EXTERNAL_REFS_RE.search(fm.group(1))
    if rm:
        ext_refs = trdd_common.parse_flow_list(rm.group(1))
    tm = _FM_TITLE_RE.search(fm.group(1))
    title = tm.group(1).strip() if tm else ""
    body = text[fm.end():]
    return _Card(uid=uid, scope=scope, ext_refs=ext_refs, body=body, title=title)


def main() -> int:
    state.init_state()
    # Context gate (TRDD-db169d9e R1): TRDD enforcement is an ai-maestro/Emasoft
    # framework convention. The janitor runs at USER scope in EVERY project, so
    # stay silent in projects that aren't ai-maestro-plugins members. (Override
    # with JANITOR_FORCE_AI_MAESTRO=1 to use TRDDs in a non-ai-maestro project.)
    if not state.project_is_ai_maestro():
        return 0

    seen = state.state_dir() / "trdd-cross-card-blindspot-seen.txt"
    root = state.project_root()

    # OPEN cards only, from `tasks/` in either scope — archived/proposals/refused
    # folders are never scanned, so a closed or never-approved card cannot appear
    # here at all. Terminal columns still parked in `tasks/` are dropped in
    # `_parse_card`.
    trdds = trdd_common.trdd_files("tasks", str(root))
    if not trdds:
        state.log_line("trdd-cross-card-blindspot", "no TRDDs in any design scope — skipping")
        return 0

    cards: dict[str, _Card] = {}
    for scope, path in trdds:
        card = _parse_card(path, scope)
        if card is not None:
            cards[card.uid] = card

    # Group open card uids by NORMALIZED shared external-refs value, preserving
    # the first-seen display spelling for the drift line.
    ref_to_uids: dict[str, list[str]] = {}
    ref_display: dict[str, str] = {}
    for uid, card in cards.items():
        for raw in card.ext_refs:
            key = _normalize_ref(raw)
            if not key:
                continue
            # EXTERNAL issue refs ONLY — a shared `TRDD-<id8>` is NOT evidence of two
            # cards blind to one defect. Pointing at a common parent/umbrella card is
            # ordinary hub-and-spoke structure: an umbrella like TRDD-G4BCRUP7 is cited
            # by many unrelated children (one per contract row), so keying on it pairs
            # up every child with every other and reports cards that have nothing to do
            # with each other.
            #
            # Worse, it is SELF-INFLICTED and unbounded: cross-linking is the remedy this
            # detector recommends, so every remedy ADDS a shared TRDD-ref and manufactures
            # the next finding. Measured immediately after shipping — cross-linking the
            # janitor#246 pair created a brand-new JPL0JU86/KI6OWCZT "pair" whose only
            # shared ref was the umbrella both had just been linked to. A check whose own
            # advice re-arms it never converges, and that is how a check gets switched off.
            if _BARE_OR_PREFIXED_TRDD_RE.match(key):
                continue
            ref_display.setdefault(key, raw.strip())
            bucket = ref_to_uids.setdefault(key, [])
            if uid not in bucket:
                bucket.append(uid)

    new_pairs: list[str] = []
    # The dedupe key of each newly-emitted pair, in the SAME order as `new_pairs`, so the
    # ones the display cap drops can have their seen-mark rolled back below.
    new_keys: list[str] = []
    for key, uids in ref_to_uids.items():
        if len(uids) < 2:
            continue
        for a, b in itertools.combinations(sorted(uids), 2):
            card_a, card_b = cards[a], cards[b]
            # SILENCER: drop the pair the moment EITHER card names the other —
            # sharing a ref is not a contradiction, only a "might not know"
            # signal, and cross-linking is exactly how that signal is cleared.
            if _references(card_a, b) or _references(card_b, a):
                continue
            dedupe_key = f"blindspot@{key}@{a}@{b}"
            msg = f"TRDD-{a} & TRDD-{b} (shared ref: {state.sanitize_for_drift_line(ref_display[key])})"
            if dedupe.emit_once(seen, dedupe_key, msg) is not None:
                new_pairs.append(msg)
                new_keys.append(dedupe_key)

    # Signal 2 (TRDD-4EKZ81MV): shared rare vocabulary, independent of any
    # shared `external-refs:` value — this is what catches a card with no
    # refs at all, or two cards that cited different issue numbers for the
    # same underlying defect (signal 1 is structurally blind to both).
    for pair, shared_words in _find_content_similarity_pairs(cards).items():
        a, b = sorted(pair)
        card_a, card_b = cards[a], cards[b]
        # Same cross-link silencer as signal 1 — naming the other card is
        # what clears BOTH signals, deliberately, so a maintainer has one
        # remedy for either finding.
        if _references(card_a, b) or _references(card_b, a):
            continue
        words_shown = ", ".join(sorted(shared_words)[:4])
        dedupe_key = f"blindspot-content@{a}@{b}@{'-'.join(sorted(shared_words))}"
        msg = f"TRDD-{a} & TRDD-{b} (shared vocabulary: {state.sanitize_for_drift_line(words_shown)})"
        if dedupe.emit_once(seen, dedupe_key, msg) is not None:
            new_pairs.append(msg)
            new_keys.append(dedupe_key)

    if not new_pairs:
        state.rotate_log_if_big("trdd-cross-card-blindspot")
        return 0

    # `emit_once` above MARKED every new pair as seen, but only `_MAX_LISTED` of them are
    # actually NAMED below — so without this, pairs past the cap are reported once as an
    # anonymous "+N more" and then never surface again, on any later fire. Forget the ones we
    # are not naming so the next fire can name them; the cap is a line-length budget, not a
    # licence to drop findings.
    for dropped_key in new_keys[_MAX_LISTED:]:
        dedupe.emit_forget(seen, dropped_key)

    shown = ", ".join(new_pairs[:_MAX_LISTED])
    if len(new_pairs) > _MAX_LISTED:
        shown += f", +{len(new_pairs) - _MAX_LISTED} more (re-reported next run)"
    print(
        f"[trdd-cross-card-blindspot] {len(new_pairs)} pair(s) may not know about each "
        f"other — {shown}. SURFACE-ONLY (no TRDD mutated); consider cross-linking or "
        f"confirm they agree."
    )

    state.rotate_log_if_big("trdd-cross-card-blindspot")
    return 0


if __name__ == "__main__":
    sys.exit(main())
