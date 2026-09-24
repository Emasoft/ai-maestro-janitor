# Shadow decision-log wiring for jev_compact.py (TRDD-N9LDHF7N card 7).
#
# jevctx.shadow.ShadowLog (vendored, scripts/lib/jevctx/shadow.py -- do not edit it, another
# worker owns jev_compaction.py/test_jev_compaction.py and this card must not touch either)
# is the generic append-only decision/outcome log. This module is the project-specific glue
# that turns jev_compaction.py's own scored items into ShadowLog calls, and answers the three
# things the vendored module deliberately leaves to its caller: where the file lives, how big
# it is allowed to get, and what a write failure means for the caller it is observing (never
# fail the compaction -- see log_decisions/log_expand_outcome).
#
# Two ShadowLog rows per fully-scored item, matching the two Noul questions
# jev_compaction.py's own score_items() actually asks (see its `_score_batch` docstring):
#   - "relevance" (jevctx's RETRIEVE_QUESTION -- `Scores.relevance` vs `relevance_threshold`)
#     -> ShadowLog kind="admit", action mirrors the item's REAL kept/elided outcome
#     (`Scores.kept`, the union of both gates) -- logged for every scored item, since every
#     item is asked this question.
#   - "decision" (DECISION_QUESTION -- `Scores.decision` vs `decision_threshold`) ->
#     ShadowLog kind="retrieve" (this project's own reading of that generic label as "a
#     signal that decides whether an item earns extra protection/retrievability" -- shadow.py
#     itself only defines the generic injected/skipped action pair, it does not prescribe
#     this mapping), action mirrors `Scores.decision_passed` -- logged ONLY for "user" items,
#     because jev_compaction.py
#     never sends a `:dec` question for any other kind (`_score_batch`: "a non-'user' item
#     still never gets a :dec question sent for it"). Logging a spurious decision=0.0 row for
#     every other item would be noise no threshold change could ever move.
#
# `replay_stats`'s own `--question relevance|decision` (the card's CLI surface) maps back onto
# exactly these two kinds (_QUESTION_TO_KIND), so a caller can retune ONE threshold without the
# OTHER question's rows (a different score/threshold pair entirely) skewing the counterfactual.
#
# A blocked or oversized item (`Scores.blocked`/`Scores.oversized`) was never actually sent to
# Jev -- jev_compaction.py fills in a sentinel Scores for it precisely so `compose()` always
# treats it as a pointer. Logging that sentinel as a real scored decision would corrupt replay,
# so both are skipped in `log_decisions`.

from __future__ import annotations

import json
import sys
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Protocol

import state
from jevctx.shadow import ShadowLog, ShadowStats
from jevctx.types import Origin

__all__ = [
    "SHADOW_LOG_NAME",
    "MAX_SHADOW_LOG_BYTES",
    "ScoredItem",
    "ItemScore",
    "shadow_log_path",
    "log_decisions",
    "log_expand_outcome",
    "replay_stats",
]

SHADOW_LOG_NAME = "jev-shadow.jsonl"

# Single-backup rotation (jev-shadow.jsonl -> jev-shadow.jsonl.1), the same shape as
# dispatch.py's own log rotation (".log"/".log.1"). 10MB of ~300-400 byte JSONL lines is tens
# of thousands of decisions -- comfortably past the card's own "about a week of use"
# acceptance bar -- without letting the file grow unbounded across months of `compact` runs.
MAX_SHADOW_LOG_BYTES = 10 * 1024 * 1024

# Card 7: "replay --threshold T [--question relevance|decision]" -- maps the CLI's question
# name onto the ShadowLog `kind` literal that carries that question's rows (see module header).
_QUESTION_TO_KIND: Mapping[str, str] = {"relevance": "admit", "decision": "retrieve"}

# Review fork finding (post-write review, TRDD-N9LDHF7N card 7): ShadowLog.stats()/.replay()
# build their internal per-item action map as `{e.item_id: e.action ...}` -- a PLAIN dict
# keyed only by item_id, with no `kind` in the key (shadow.py's own `stats`/`replay`). Logging
# the admit AND retrieve rows for a "user" item under the SAME item_id therefore collapses to
# ONE slot (last write wins -- the retrieve row, appended second), so the admit row's real
# "kept"/"elided" action is silently discarded whenever the raw file is read through the
# vendored module's own public `.stats()`/`.replay()` (not just through this module's own
# kind-filtered `replay_stats`, which was already immune). Concretely: an elided "user" item
# would stop counting as a false negative in `ShadowLog.load(path).stats()` the moment it also
# got a retrieve row. Suffixing the retrieve row's item_id makes the two rows collision-proof
# in ANY reader, not just this module's own filtered path -- `log_expand_outcome` never needs
# to know about the suffix, since it always logs the bare id, which only the admit row (the
# one "was this elided" is actually about) can ever match.
_RETRIEVE_ROW_ID_SUFFIX = "#decision"


class ScoredItem(Protocol):
    """The `jev_compaction.Item` fields this module reads -- a structural Protocol instead
    of importing `jev_compaction` directly, so this module carries no dependency on that
    module's own httpx-requiring import chain, and no coupling to its in-flight changes.

    Declared as read-only `@property` members, not plain mutable annotations: `Item` is a
    frozen dataclass, and a plain `id: str`-style Protocol attribute requires a SETTER too
    (pyright: "id is not read-only in protocol") -- a frozen dataclass instance would then
    never structurally satisfy it.
    """

    @property
    def id(self) -> str: ...
    @property
    def kind(self) -> str: ...
    @property
    def text(self) -> str: ...
    @property
    def tokens(self) -> int: ...
    @property
    def turn(self) -> int: ...


class ItemScore(Protocol):
    """The `jev_compaction.Scores` fields this module reads -- read-only for the same reason
    as `ScoredItem` above (`Scores` is also a frozen dataclass)."""

    @property
    def relevance(self) -> float: ...
    @property
    def decision(self) -> float: ...
    @property
    def oversized(self) -> bool: ...
    @property
    def kept(self) -> bool: ...
    @property
    def decision_passed(self) -> bool: ...
    @property
    def blocked(self) -> bool: ...


def shadow_log_path() -> Path:
    """`<project>/.janitor/state/jev-shadow.jsonl` -- `.janitor/` is gitignored project-wide
    (see the repo's own .gitignore), so this never lands in the repo tree, per the card."""
    return state.state_dir() / SHADOW_LOG_NAME


def _rotate_if_oversized(path: Path) -> None:
    """Single-backup rotation: `path` -> `path.1` (overwriting any older one) once `path`
    crosses `MAX_SHADOW_LOG_BYTES`. Never raises: a rotation failure degrades to "keep
    appending to the oversized file" rather than aborting the log entirely -- write failures
    are the caller's own concern (log_decisions/log_expand_outcome), this is just growth
    control and must not itself become a NEW way for shadow logging to break a compaction.

    Checked once per `log_decisions`/`log_expand_outcome` call, not once per line: a single
    `compact` run over a transcript with thousands of items can therefore push the file past
    `MAX_SHADOW_LOG_BYTES` by that call's own size before the NEXT call rotates it -- an
    acceptable, deliberate looseness for an observability side channel (the cap bounds
    long-run growth across many `compact` runs, not the peak size of any one run)."""
    try:
        if not path.exists() or path.stat().st_size <= MAX_SHADOW_LOG_BYTES:
            return
        backup = path.with_name(path.name + ".1")
        path.replace(backup)
    except OSError as exc:
        print(f"jev-shadow: rotation failed, appending to the oversized file: {exc}", file=sys.stderr)


def _open_log(path: Path) -> ShadowLog:
    _rotate_if_oversized(path)
    return ShadowLog(path=path)


def log_decisions(
    items: Iterable[ScoredItem],
    scores: Mapping[str, ItemScore],
    *,
    relevance_threshold: float,
    decision_threshold: float,
) -> None:
    """Append one "admit" row per scored item, plus one "retrieve" row for each item that was
    actually asked the decision question -- see the module header for which is which. Called
    once per real `compact` run, right after `jc.score_items` returns: this logs from the
    scores jev_compact.py already has, never from a hook inside jev_compaction.py itself.

    A write failure (a read-only `.janitor/`, a full disk, a permissions error) is reported on
    stderr and swallowed: shadow logging is an observability side channel, and a compaction
    that already scored and is about to write its real output must never fail because the
    SIDE log couldn't be written (card 7's own requirement).
    """
    try:
        log = _open_log(shadow_log_path())
        for it in items:
            sc = scores.get(it.id)
            if sc is None or sc.oversized or sc.blocked:
                continue  # never actually scored -- see module header
            origin = Origin(source=f"item:{it.kind}", ref=it.id, turn=it.turn)
            log.decision(
                kind="admit", item_id=it.id, score=sc.relevance,
                threshold=relevance_threshold, action="kept" if sc.kept else "elided",
                tokens=it.tokens, origin=origin, text=it.text, turn=it.turn,
            )
            if it.kind == "user":
                # `_RETRIEVE_ROW_ID_SUFFIX`: keeps this row's item_id distinct from the admit
                # row just logged above -- see that constant's own comment for why sharing
                # `it.id` between the two corrupts the vendored ShadowLog.stats()/.replay().
                log.decision(
                    kind="retrieve", item_id=f"{it.id}{_RETRIEVE_ROW_ID_SUFFIX}",
                    score=sc.decision, threshold=decision_threshold,
                    action="injected" if sc.decision_passed else "skipped",
                    tokens=it.tokens, origin=origin, text=it.text, turn=it.turn,
                )
    except OSError as exc:
        print(f"jev-shadow: decision log write failed, compaction continues: {exc}", file=sys.stderr)


def log_expand_outcome(item_id: str, *, turn: int = 0) -> None:
    """Append an "expand" outcome row. An expand of an id `compact` had logged as elided is a
    false negative (see `ShadowLog.false_negative_rate`'s own docstring) -- this is the only
    hook `expand` needs; the matching against a prior decision happens later, by item_id, when
    the log is read (`ShadowLog.stats`/`.replay`). `item_id` is always the BARE id (never
    `_RETRIEVE_ROW_ID_SUFFIX`-suffixed): that matches only the admit row, which is the one
    "was this elided" is actually about -- an item's retrieve row, if any, is a separate
    question entirely (see `log_decisions`).

    `turn` defaults to 0: a one-shot `expand` invocation has no live turn counter the way
    `compact` has each item's own `.turn` -- harmless, since no stats computation in ShadowLog
    reads `turn` at all (its `_summarise` keys only on item_id/score/action/tokens).
    """
    try:
        log = _open_log(shadow_log_path())
        log.outcome(kind="expand", item_id=item_id, turn=turn)
    except OSError as exc:
        print(f"jev-shadow: outcome log write failed: {exc}", file=sys.stderr)


def replay_stats(threshold: float, *, question: str, path: Path | None = None) -> ShadowStats:
    """What `threshold` would have produced for just `question`'s own rows -- card 7's
    `replay --threshold T --question relevance|decision`.

    `ShadowLog.replay()` applies ONE threshold to every decision it holds regardless of
    `kind` -- correct when a log only ever carries one question's rows, wrong here since
    `log_decisions` logs two per item. So this filters the persisted JSONL down to the rows
    for the requested question's `kind` (plus every outcome row, which carries no `kind` and
    is always relevant to the false-negative count) into a scratch file, then delegates the
    actual counterfactual math to the vendored `ShadowLog.load`/`.replay` -- no
    reimplementation of its private `_counterfactual`.
    """
    if question not in _QUESTION_TO_KIND:
        raise ValueError(f"unknown question {question!r}, expected one of {sorted(_QUESTION_TO_KIND)}")
    kind = _QUESTION_TO_KIND[question]
    source = path if path is not None else shadow_log_path()

    kept_lines: list[str] = []
    if source.exists():
        try:
            with source.open("r", encoding="utf-8") as fh:
                for line in fh:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        obj = json.loads(stripped)
                    except json.JSONDecodeError:
                        continue  # a torn final write -- ShadowLog.load skips these too
                    if obj.get("type") == "decision" and obj.get("kind") != kind:
                        continue  # the OTHER question's row
                    kept_lines.append(stripped)
        except OSError as exc:
            print(f"jev-shadow: replay read failed, treating as empty: {exc}", file=sys.stderr)
            kept_lines = []

    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8") as tmp:
        for line in kept_lines:
            tmp.write(line + "\n")
        tmp_path = Path(tmp.name)
    try:
        return ShadowLog.load(tmp_path).replay(threshold)
    finally:
        tmp_path.unlink(missing_ok=True)
