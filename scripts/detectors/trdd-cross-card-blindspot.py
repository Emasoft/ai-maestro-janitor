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

The predicate: a PAIR of OPEN cards sharing an `external-refs:` entry that do
NOT reference each other (in either card's `external-refs:` or body). Sharing
a ref is NOT a contradiction — a parent and its derived task, a detector and
its fix, legitimately cite the same issue — so this NEVER asserts the two
cards disagree. It says only "these two may not know about each other";
cross-referencing (once either side names the other) is the correct silencer.

SURFACE-ONLY: this detector mutates ZERO TRDD files, ever. Zero model tokens
— the whole check is a script pairing up `external-refs:` values. Terminal
and archived/refused cards are excluded (a closed card cannot be re-litigated
and the archived/refused folders are not scanned at all).

Slow-moving board hygiene — daily cadence; per-(ref, pair) seen-file dedupe.
"""

from __future__ import annotations

import itertools
import re
import sys
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


@dataclass
class _Card:
    """Everything this detector needs from ONE open TRDD card."""

    uid: str
    scope: str
    ext_refs: list[str] = field(default_factory=list)  # raw external-refs elements
    body: str = ""


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


def _parse_card(path: Path, scope: str) -> _Card | None:
    """Parse one TRDD file into a `_Card`, or None when it has no usable id."""
    uid = trdd_common.extract_uid(path.name)
    if uid is None:
        return None
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            head = f.read(trdd_common.RECONCILE_BYTES)
    except OSError:
        return None
    fm = trdd_common.FRONTMATTER_RE.match(head)
    if not fm:
        return None
    _, column = trdd_common.parse_state_text(head)
    if trdd_common.is_terminal_column(column):
        return None
    ext_refs: list[str] = []
    rm = _FM_EXTERNAL_REFS_RE.search(fm.group(1))
    if rm:
        ext_refs = trdd_common.parse_flow_list(rm.group(1))
    body = head[fm.end():]
    return _Card(uid=uid, scope=scope, ext_refs=ext_refs, body=body)


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
            msg = f"TRDD-{a} & TRDD-{b} ({state.sanitize_for_drift_line(ref_display[key])})"
            if dedupe.emit_once(seen, dedupe_key, msg) is not None:
                new_pairs.append(msg)

    if not new_pairs:
        state.rotate_log_if_big("trdd-cross-card-blindspot")
        return 0

    shown = ", ".join(new_pairs[:_MAX_LISTED])
    if len(new_pairs) > _MAX_LISTED:
        shown += f", +{len(new_pairs) - _MAX_LISTED} more"
    print(
        f"[trdd-cross-card-blindspot] {len(new_pairs)} pair(s) cite the same issue and may "
        f"not know about each other — {shown}. SURFACE-ONLY (no TRDD mutated); "
        f"consider cross-linking or confirm they agree."
    )

    state.rotate_log_if_big("trdd-cross-card-blindspot")
    return 0


if __name__ == "__main__":
    sys.exit(main())
