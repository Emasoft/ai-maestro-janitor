"""The compacted-context composer (TRDD-RAEGS1D5 card 3, part A).

Pure functions over data: extract the OLD transcript's items, build a small task digest,
score each item through Jev, then compose the final injected document. No side effects
(no file writes, no subprocess calls) -- the caller (``scripts/jev_compact.py``, part B)
owns I/O and wires the Jev client / TRDD STATE heads in.

Only ever imported by the PEP-723 script ``scripts/jev_compact.py`` (which needs
``httpx`` via jevctx's HTTP clients) -- never by a stdlib-only hook script. This module
itself has no third-party dependency; it only touches the vendored ``jevctx`` package,
which lives one directory up (``scripts/lib/jevctx/``).
"""

from __future__ import annotations

import json
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

# WHY: this file lives in scripts/lib/, a sibling of scripts/lib/jevctx/ -- adding this
# directory to sys.path lets `import jevctx...` work whether this module is imported by
# scripts/jev_compact.py (which already does the same insert) or directly by a test that
# never ran that script.
_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import jsonl_walk  # noqa: E402  -- needs the sys.path line above; stdlib-only, shared byte-safe JSONL walk (TRDD-DQXMND59 stage 3)
import transcript_roles  # noqa: E402  -- needs the sys.path line above; stdlib-only, shared classifier
from jev_expand import attachment_item_text, tool_result_text  # noqa: E402  -- needs the sys.path line above; stdlib-only, the ONE attachment-text / tool-result-text rule, shared with `expand` and the cross-/clear verifier (TRDD-I40IKPWU)
from jevctx import scorer as _scorer  # noqa: E402
from jevctx.budget import Batch, BudgetPlanner  # noqa: E402
from jevctx.openrouter import JevBlockedError  # noqa: E402  -- TRDD-1ETALGDG, see score_items
from jevctx.pipeline import RETRIEVE_QUESTION, format_pointer  # noqa: E402
from jevctx.segments import segment  # noqa: E402  -- card 6, TRDD-88DOI824, see _segment_tool_result
from jevctx.tokens import estimate_tokens  # noqa: E402
from jevctx.types import (  # noqa: E402
    MAX_QUESTIONS_PER_REQUEST,
    JevClient,
    JevValidationError,
    NoulAnswer,
    Origin,
    Pointer,
    Question,
    ScoreItem,
)

__all__ = [
    "Item",
    "Scores",
    "NoDigest",
    "RETRIEVE_QUESTION",
    "DEFAULT_RELEVANCE_THRESHOLD",
    "ConversationWindow",
    "extract_items",
    "split_conversation",
    "build_digest",
    "score_items",
    "compose",
]

# "event" (TRDD-RAEGS1D5, 2026-09-23 real-transcript bug fix): a `type: "user"` JSONL entry
# whose text is NOT human-authored -- a task notification, most commonly -- still carries
# real informational content (an agent's report) worth scoring/inlining, so it is kept as an
# item rather than dropped; it is just never counted as a human message. See
# `is_human_record` and `build_digest`'s "last three human messages" ordering, which relies
# on `kind == "user"` meaning genuinely human now.
#
# "control" (TRDD-D7RLXAN1): a content-free owner input -- a bare "resume"/"continue"/argument-
# less "/compact" (`transcript_roles.is_control_input`). It used to be demoted to "event"
# (TRDD-DZ1KOGAC), which put the owner's own words into the SCORED stream, where a score could
# drop them. It is conversation now (see `split_conversation`): kept verbatim, never scored,
# and still never `kind == "user"`, so `build_digest` and the newest-owner pick ignore it
# exactly as DZ1KOGAC intended.
# TRDD-FCYOSWWB widened it: "control" is content-free OR a harness-admin command (/login,
# /model, /plugin ...) -- neither is an instruction to the agent.
ItemKind = Literal["user", "assistant", "tool", "event", "control"]

# Entry `type`s that ever carry a extractable item (spec: skip `system` entries and the
# auxiliary types -- mode, file-history-snapshot, last-prompt, queue-operation -- outright).
# "attachment" (TRDD-RAEGS1D5 defect 4, orchestrator scope extension 2026-09-23): Claude Code
# also writes a MID-TURN queued owner message (typed while a turn was running) or a queued
# task-notification delivery as `type: "attachment"`, `attachment.type == "queued_command"` --
# a real 2026-09-23 session transcript measured these carrying the owner's own words ("you are
# slow") that `_WALKED_ENTRY_TYPES` used to drop entirely. Most other `attachment` entries
# (`hook_success`, `hook_additional_context`, ...) are hook noise, filtered inside
# `extract_items` itself by `attachment.type`, not here.
_WALKED_ENTRY_TYPES = {"user", "assistant", "attachment"}

# Truncation cap for a remembered tool_use `input` (spec: "name+input truncated to 300
# chars") -- long enough to identify the call, short enough that a page of `Bash` args
# doesn't dominate the digest/score request.
_TOOL_INPUT_TRUNCATE = 300

# TRDD-RAEGS1D5 defect 1 (adversarial review of commit 2353a88a): the ORIGINAL fix opened a
# whole-turn skip window on any heartbeat fire, which silently dropped REAL work a
# `[janitor-resume]` turn does (reads cards, dispatches agents, edits, commits) -- outnumbering
# the noise it meant to cut. Narrowed to pattern-match exactly the two quiet items a heartbeat
# turn always produces: the dispatcher-stub call (this marker, checked against the tool_use's
# raw JSON `input` before truncation) and its paired result; everything else in the turn --
# other tool calls, other tool results, real assistant prose -- is now kept like any other item.
_DISPATCHER_STUB_MARKER = "dispatcher-stub.py"

# Pointer first-line preview cap (spec: `"<first line ≤80 chars>"`).
_POINTER_PREVIEW_CHARS = 80


@dataclass(frozen=True)
class Item:
    """One scorable/inlinable unit of the OLD transcript.

    `id` = "<entry uuid>:<block index>" -- the block index is the position in the RAW
    content list of the entry that produced it (including blocks that were themselves
    skipped, e.g. `thinking`/`tool_use`), so the id stays a valid pointer back into the
    original JSONL for `jev_compact.py expand` to resolve, and is stable across re-runs
    because it depends only on the transcript's own content, never on extraction order.

    Card 6 (TRDD-88DOI824): a large tool result is split into several Items, one per
    `jevctx.segments.segment()` piece, id "<entry uuid>:<block index>@<a>-<b>" (1-based,
    inclusive line numbers into the block's own raw text) -- see `_segment_tool_result`.
    `protected=True` marks a segment whose structural kind is `stacktrace` or `diff`: it
    ranks above a relevance-only item in `compose()`'s eviction/pointer-slot ordering. Always
    `False` for a non-segmented Item.
    """

    id: str
    kind: ItemKind
    text: str
    tokens: int
    ts: str | None
    turn: int
    protected: bool = False

    def __post_init__(self) -> None:
        # TRDD-DQXMND59 follow-up (adversarial review, 2026-09-24, finding C): `json.loads`
        # accepts a LONE surrogate escape (e.g. an emoji Node cut in half writing the
        # transcript, `"\ud83d"` with no paired low surrogate) and hands back a `str` that
        # LOOKS fine but raises `UnicodeEncodeError` on the first `.encode("utf-8")` --
        # `compose()`'s own byte-budget accounting does this on every item's `.text`. Fixed
        # ONCE here, at Item construction (every extraction path and every test builds an
        # Item, none construct the text a caller already validated), rather than at each of
        # the dozen-plus `.encode("utf-8")` call sites in `compose()`.
        fixed = jsonl_walk.drop_lone_surrogates(self.text)
        if fixed is not self.text:
            object.__setattr__(self, "text", fixed)


@dataclass(frozen=True)
class Scores:
    """The Noul answer for one item, plus the derived facts callers need.

    `kept`/`oversized` are computed here (not left for `compose` to recompute) because
    `score_items` is the one place that knows the threshold it used -- `compose`'s
    signature has no threshold parameters, it just trusts these booleans.
    """

    relevance: float
    oversized: bool
    kept: bool
    # TRDD-1ETALGDG followup: True iff this item was NEVER sent to Jev at all -- a provider
    # firewall block or an oversized batch survived every split retry `score_items` tried
    # (see `_score_batch_resilient`). Distinct from an ordinary below-threshold item (which
    # WAS judged and found not relevant): `compose()` renders a blocked item's pointer with
    # its own "unscored (provider firewall)" note so the model can tell "Jev never saw this"
    # apart from "Jev saw it and it wasn't worth keeping". Defaults to `False` so every
    # existing `Scores(...)` call site (including every test that builds one by hand) needs
    # no change.
    blocked: bool = False


# TRDD-D7RLXAN1 (owner directive 2026-09-24: "assistant prose and user prose (the messages
# exchanges) should be all kept intact"): the item kinds that are the conversation itself.
# They are never sent to Jev as scored items -- a prompt sentence cannot guarantee a threshold
# outcome, so the guarantee is that no score exists to drop them (see `split_conversation`).
_CONVERSATION_KINDS = frozenset({"user", "assistant", "control"})


@dataclass
class ConversationWindow:
    """What the session's LAST compaction left in context, recorded by `extract_items`.

    TRDD-D7RLXAN1: "all" prose means all prose since the session's last `compact_boundary`;
    the prose before it is represented by Claude Code's own compaction summary (`summary`, kept
    verbatim). Filled in place by `extract_items(..., window=...)`, the same out-parameter idiom
    as `segmentation_failures`, so the transcript is still walked once.

    `boundary_turn` is the item counter when the last boundary line was read (None: no
    boundary); `preserved_uuids` is that boundary's `compactMetadata.preservedMessages.allUuids`
    (pre-boundary entries Claude Code kept verbatim in the new context); `summary` is the
    `isCompactSummary` text paired to THAT boundary (None when the session died between the two
    lines -- never a stale earlier summary, see `extract_items`).

    "Verbatim" here has ONE exception (TRDD-DQXMND59 stage 3, item G): a lone (unpaired) UTF-16
    surrogate escape in the raw transcript (e.g. an emoji a writer's own bug cut in half) is
    replaced with U+FFFD -- unavoidable, since a lone surrogate cannot be encoded to UTF-8 at
    all, and `summary` is written into the final document as UTF-8 by `compose()`. `summary` is
    never an `Item` (so `Item.__post_init__` never touches it) -- sanitized explicitly, at the
    point it is set in `extract_items`, via `jsonl_walk.drop_lone_surrogates`.
    """

    boundary_turn: int | None = None
    preserved_uuids: frozenset[str] = frozenset()
    summary: str | None = None
    # The boundary's `preservedMessages.anchorUuid`: the uuid of the summary entry that belongs
    # to it (measured on fd5cc3e0, both boundaries). None when no boundary is pending an anchor.
    pending_anchor: str | None = None

    def is_live(self, item: Item) -> bool:
        """True iff `item` was in the context the cleared session actually had: after the last
        boundary, or preserved across it. `turn` never decreases during the walk, so every item
        appended after the boundary line has `turn >= boundary_turn` and every earlier one less."""
        return (self.boundary_turn is None or item.turn >= self.boundary_turn
                or item.id.split(":", 1)[0] in self.preserved_uuids)


def split_conversation(
    items: list[Item], window: ConversationWindow
) -> tuple[list[Item], list[Item], int]:
    """`(conversation, scored, pre_boundary)` -- TRDD-D7RLXAN1's enforcement split, extended by
    TRDD-350W5II2 to apply the SAME liveness predicate to tool/event items.

    `conversation`: every LIVE owner/assistant/control item, chronological -- rendered verbatim
    by `compose(conversation=...)`, never scored. `scored`: every LIVE tool and event item --
    the only items `score_items` ever sees. `pre_boundary`: count of tool/event items dropped
    from `scored` because `window.is_live` said they predate the last boundary and were not
    preserved across it (TRDD-350W5II2: `score_items` used to see every tool/event item
    including these, most of the 168s/7075-item cost on 4eb7bf5d -- scoring a pre-boundary tool
    result against the CURRENT digest judges it against a task it predates). Neither dropped
    prose nor a dropped pre-boundary tool/event item becomes unreachable: `window.summary`
    covers the prose (see its own docstring for the ONE exception to "verbatim" -- a lone
    surrogate becomes U+FFFD), and `jev_compact.py expand <id>` resolves ANY item, live or not,
    from the raw JSONL by uuid -- this function only decides what gets SCORED and RENDERED.
    `conversation`'s own items are already `Item`s -- `Item.__post_init__` sanitizes the same
    way, so this list needs no separate note.
    """
    conversation = [it for it in items if it.kind in _CONVERSATION_KINDS and window.is_live(it)]
    non_conversation = [it for it in items if it.kind not in _CONVERSATION_KINDS]
    scored = [it for it in non_conversation if window.is_live(it)]
    pre_boundary = len(non_conversation) - len(scored)
    return conversation, scored, pre_boundary


class NoDigest(Exception):
    """Raised by `build_digest` when there is nothing to build a digest from.

    Neither a human message nor a TRDD STATE head exists -- the caller declines Jev
    compaction entirely rather than score every item against an empty/meaningless task.
    """


# Card 5 (TRDD-HWF3QFAB): the relevance question is now `jevctx.pipeline.RETRIEVE_QUESTION`
# (vendored verbatim, TRDD-RAEGS1D5 card 4) instead of a local copy -- the old local copy
# mixed an ADMIT-style clause into RETRIEVE's own wording and invented its own true/false
# criteria text (written before pipeline.py was vendored, from a quotation in
# reports/compaction-replacement/20260922_205137+0200-jev-compaction-study.md §C, not from
# source), which measurably inflated relevance ("needed later" is a keep-biased ADMIT
# question, not "relevant right now") -- see reports/compaction-replacement/
# 20260923_200805+0200-jev-reference-gap-analysis.md row 13.

DEFAULT_RELEVANCE_THRESHOLD = 0.5

# TRDD-HWF3QFAB (card 5) sized the planner for a per-kind split (16 two-question "user"
# items vs 32 one-question others). TRDD-R9UXOSR5 retired the decision question and with it
# the user group -- every scored item is tool/event and asked relevance only, so one batch
# size remains: a full MAX_QUESTIONS_PER_REQUEST items, one question each.
_BATCH_MAX_QUESTIONS = MAX_QUESTIONS_PER_REQUEST

# "BudgetPlanner allows it cleanly, otherwise keep the conservative planning and record
# why" (this card's own spec text) -- it does NOT hold cleanly: jevctx.types's own
# STATE_PLUS_ALL_QUESTIONS_TOKENS=64000 / STATE_PLUS_LONGEST_QUESTION_TOKENS=32000 do not
# match the OpenRouter-routed Jev backend this project actually calls
# (jevctx.provider.make_client -> OpenRouterJevClient, model "~typesafe/jev-latest").
# MEASURED live against the 4.7 MB real transcript this session (TRDD-HWF3QFAB): a 32-item
# "other"-group batch at state_tokens=27163 + question_tokens=3862 = 31025 estimated total
# failed with HTTP 400 `{"error_type": "max_tokens_exceeded"}`; a same-shaped batch at
# 26384 total succeeded; a synthetic 32-question batch with a small state (~2000 total)
# also succeeded -- so the failure tracks the REQUEST'S TOTAL estimated size, not the
# question count alone, and the real ceiling sits well under jevctx's advertised 32000/
# 64000, somewhere in the ~26-31k band. `BudgetPlanner`'s own "all questions" cap exists
# to bound exactly this (state + every question), so this overrides it to a value with
# real margin below that measured band, rather than trusting the vendored constant --
# `max_questions` above (16/32 items) still applies on top of this and is usually the
# tighter cap for the "other" group's typically-small notification/assistant items; this
# only kicks in for the rarer batch that happens to hold several large tool outputs.
_SAFE_STATE_PLUS_ALL_QUESTIONS_TOKENS = 20_000

# TRDD-1ETALGDG: a real-transcript compaction hit a Cloudflare edge block (`JevBlockedError`)
# and a live HTTP 400 `max_tokens_exceeded` (a batch `BudgetPlanner` estimated as fitting but
# didn't) -- both used to abort the WHOLE compaction on the first bad batch. `score_items` now
# splits a batch that hits either in half and retries the halves (see `_score_batch_resilient`),
# bounded by two independent caps so a persistently-blocking backend can't turn one bad batch
# into an unbounded retry storm: `_MAX_SPLIT_DEPTH` bounds how many times any ONE batch is
# halved (5 halvings takes the largest batch this module ever plans, 32 items -- the
# `_BATCH_MAX_QUESTIONS` cap -- down to 1: 32->16->8->4->2->1), and `_MAX_RETRIED_REQUESTS`
# bounds the TOTAL extra (non-original) requests across the whole `score_items` call.
_MAX_SPLIT_DEPTH = 5
_MAX_RETRIED_REQUESTS = 64

# The exact `error_type` OpenRouter's JSON body carries for the live 400 commit 61cad99c
# measured (`{"error_type": "max_tokens_exceeded"}`) -- `_error_detail` folds an error body
# with no top-level "error"/"message" key into `str(payload)`, so this substring survives into
# `JevValidationError`'s own message regardless of the dict's exact key order/quoting.
_MAX_TOKENS_EXCEEDED_MARKER = "max_tokens_exceeded"


def _is_max_tokens_exceeded(exc: JevValidationError) -> bool:
    """True iff `exc` is the live HTTP 400 `max_tokens_exceeded` response (a batch the
    planner's own token ESTIMATE thought fit, but the backend's real tokenizer didn't) --
    as opposed to any OTHER `JevValidationError` (a 404/413/422/malformed-response bug in
    the request shape itself, which splitting the batch cannot fix and must not retry)."""
    return _MAX_TOKENS_EXCEEDED_MARKER in str(exc)


class _RetryBudget:
    """Thread-safe counter for `score_items`'s `_MAX_RETRIED_REQUESTS` cap.

    Shared across every batch's split-retry recursion (one instance per `score_items` call),
    not per-batch: `ThreadPoolExecutor` runs many ORIGINAL batches concurrently, and the cap
    exists to bound the EXTRA load a block/oversize storm puts on the backend across all of
    them together, not to give each batch its own separate budget.
    """

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._used = 0
        self._lock = threading.Lock()

    def take(self) -> bool:
        """Reserve one retried request; `False` if the cap is already spent."""
        with self._lock:
            if self._used >= self._limit:
                return False
            self._used += 1
            return True


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit]


def _entry_primary_text(entry: dict[str, Any]) -> str:
    """The one text string a `type: "user"` entry is classified by.

    The plain string `message.content`, or the first `text`-type block's text when content is
    a list of blocks. A `tool_result`-only entry (no `text` block at all) yields `""` --
    deliberately: it must never be mistaken for a heartbeat body (see `_is_heartbeat_entry`).
    Mirrors `transcript_roles._primary_text` (private there, so duplicated rather than reached
    into across the module boundary) -- only `_is_heartbeat_entry` still needs it directly;
    `is_human_record` now delegates entirely to `transcript_roles.classify_record`.
    """
    content = entry.get("message", {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                return block.get("text", "")
    return ""


def is_human_record(entry: dict[str, Any]) -> bool:
    """True iff this transcript JSONL entry is genuine human input.

    TRDD-RAEGS1D5 (2026-09-23): originally a bespoke two-way heuristic here; the orchestrator's
    same-day scope extension replaced it with `transcript_roles.classify_record`'s nine-rule,
    real-transcript-measured classifier (task notifications, compact summaries, local-command
    wrappers, peer/coordinator messages, ... -- a two-way test cannot tell these apart). Kept as
    a thin wrapper -- `extract_items` now calls `classify_record` directly and no longer needs
    the plain boolean -- purely so a caller (and this module's own tests) that only cares "was
    this the human" doesn't have to know the wider role vocabulary exists.
    """
    return transcript_roles.classify_record(entry) == "human"


def _is_heartbeat_entry(entry: dict[str, Any]) -> bool:
    """True iff this `type: "user"` entry is the janitor heartbeat fire's OWN initiating prompt.

    TRDD-RAEGS1D5 defect 2 (adversarial review of commit 2353a88a): detect ONLY by the fire's
    own fixed prefix, never by `turnOrigin == "scheduled"` -- the owner's own CronCreate/`/loop`
    jobs are scheduled too, and a scheduled prompt is requested work, not a machine-only fire.
    Folding it into "heartbeat" would have DROPPED it outright; a scheduled prompt that lacks
    the prefix now instead reaches `transcript_roles.classify_record`, which downgrades it to
    role "system" -> kind "event" (kept, just never counted as the human -- see `extract_items`).
    This function's OWN job stays narrower than "system": even a `[janitor-heartbeat]`-prefixed
    prompt classifies as role "system" too, but its own prompt text carries zero information (it
    is always the same fixed dispatcher-stub instruction) -- unlike `<local-command-stdout>` or
    an interrupt marker, which ARE kept as "event" -- so `extract_items` calls this FIRST and
    drops the match entirely, before `classify_record` ever runs on it.
    """
    return _entry_primary_text(entry).startswith(transcript_roles.HEARTBEAT_PREFIX)


# Card 6 (TRDD-88DOI824): "tool results above about 1,000 tokens" -- below this, a tool
# result stays exactly the pre-card-6 shape (one all-or-nothing Item); segmenting a small
# result would cost more in per-segment pointer/header overhead than it could ever save.
_SEGMENT_THRESHOLD_TOKENS = 1000

# Card 6: "Protected kinds stacktrace and diff rank above relevance-only items in evict_key"
# -- see `Item.protected` and `compose()`'s `evict_key`/
# `_pointer_priority`/admission-sort tuples, all of which fold this in as a top tier.
# (TRDD-R9UXOSR5: it used to sit between `decision_passed` and relevance; the decision
# question's retirement left it the highest tier among scored items.)
_PROTECTED_SEGMENT_KINDS = frozenset({"stacktrace", "diff"})


def _source_item_id(item_id: str) -> str:
    """The tool-result item `item_id` came from -- for a segment id (`<uuid>:<n>@<a>-<b>`,
    see `_segment_tool_result`) this strips the `@a-b` suffix so every segment of the SAME
    tool result maps to one shared key; a non-segmented id (no ``@``) is already its own
    source and is returned unchanged.

    Card 6 follow-up (coordinator review of commit 3006e92f): `compose()` uses this to cap
    the `protected`-kind priority boost to at most one segment per source item -- see its
    own comment for the real-transcript defect this closes (three segments of ONE diff
    outcompeting three OTHER tool results for the same fixed budget).
    """
    return item_id.split("@", 1)[0]


# Card 6: a Read tool result's `cat -n`-style output prefixes EVERY line with
# "<spaces><digits><TAB>" -- e.g. "     1\tdef foo():". `jevctx.segments.detect_kind`'s
# `_looks_tabular` check counts exactly one tab per line as tabular when every line's count
# matches, so this prefix alone misdetects numbered code as `kind="table"` (measured: 2,792
# of 2,848 real segments) and cuts it every 20 lines (`_ROWS_PER_SEGMENT`) regardless of what
# the code actually is. `_detection_view` strips it for detection only, never for the stored
# text -- see that function's own docstring.
_SEGMENT_LINE_NUM_PREFIX = re.compile(r"^\s*\d+\t")


def _detection_view(text: str) -> str:
    """`text` with the Read-style line-number prefix (`_SEGMENT_LINE_NUM_PREFIX`) stripped
    from every line, for `jevctx.segments.segment()`'s KIND DETECTION AND CUT POINTS ONLY --
    never for the text a segment Item actually stores or renders (`_segment_tool_result`
    slices the CALLER's original, unstripped lines with the `line_span` this view produces).

    The strip is per-LINE and removes only leading characters within a line -- it never
    changes line COUNT or merges/splits a line -- so a `Segment.line_span` computed against
    this view is guaranteed to index the original's lines one-to-one, whether or not any line
    actually matched the prefix (a no-op line passes through unchanged).

    EXCEPT one edge case, guarded against below: `text`'s FINAL line, if it carries no
    trailing newline (a real, unterminated tail is the normal case -- `splitlines` requires
    none), can have the prefix match its ENTIRE content (e.g. a Read line whose source line is
    blank: raw text "   311\\t" with nothing after the tab). Stripped naively, that line
    becomes the empty string -- and `"".join(...)` would then contribute ZERO bytes for it,
    so `segment()`'s OWN internal `text.splitlines(keepends=True)` re-split of the joined
    result would see ONE FEWER line than this function's caller does, shifting every
    `line_span` after it by one and silently dropping the tail from `_segment_tool_result`'s
    slice (measured on a real 258 MB transcript: 4 bytes missing, byte-for-byte "311\\t", the
    losslessness assertion in `_segment_tool_result` is what caught it). A line that would
    vanish entirely is left UNSTRIPPED instead -- a no-op line already passes through
    unchanged per the paragraph above, so this is the same fallback, just triggered by an
    edge case rather than a non-match.
    """
    pieces = []
    for line in text.splitlines(keepends=True):
        stripped = _SEGMENT_LINE_NUM_PREFIX.sub("", line, count=1)
        pieces.append(stripped if stripped else line)
    return "".join(pieces)


def _segment_tool_result(
    item_id_base: str, name: str, tool_input: str, result_text: str, ts: str | None, turn: int,
    *, segmentation_failures: list[str] | None = None,
) -> list[Item]:
    """One `tool_result` block -> one or more scorable/inlinable Items.

    Card 6 (TRDD-88DOI824): 601 real tool results of 2k-24k tokens held 32% of all tool
    tokens in the three largest real transcripts, each all-or-nothing against the budget.
    Above `_SEGMENT_THRESHOLD_TOKENS`, `jevctx.segments.segment()` (vendored, see
    `jevctx/VENDORED.md`) splits `result_text` into independently scoreable/admittable
    pieces instead of one big Item.

    Segmented on `result_text` ALONE, never the `name(input)\\n` prefix this function adds
    for score-time context below: that prefix is this project's own synthetic addition, never
    a transcript byte, so including it in what gets segmented would (1) violate "a segment is
    an exact slice of the original" and (2) shift every segment's line numbers by one relative
    to `jev_expand.extract_block`, which returns only the RAW tool_result content for a
    `tool_result` block -- `expand`'s `<uuid>:<n>@<a>-<b>` slicing depends on the two agreeing.

    Below the threshold, or when segmentation yields at most one piece anyway (nothing to
    split), this returns the PRE-card-6 shape unchanged: one Item, id `item_id_base` (no `@`
    suffix), text `name(input)\\nresult`.

    Adversarial review (TRDD-88DOI824): the first version of this function let ANY failure in
    the segmentation path -- a `segment()` bug on unusual real content, or the losslessness
    check itself firing -- propagate all the way out of `extract_items()`, aborting the WHOLE
    `compact` run over ONE bad tool result (this is not hypothetical: the real-data
    acceptance run hit exactly this on the 258 MB transcript before `_detection_view`'s
    line-vanishing fix, below). That is a real regression in this file's own established risk
    posture -- `_score_batch_resilient` exists specifically so one bad batch never sinks the
    whole call -- so segmentation failures degrade the SAME way score-batch failures do: a
    stderr finding line, then the pre-card-6 whole-item shape, never a crash. The verbatim
    guarantee still holds either way (a segment's text is always sliced from `result_text`, or
    `result_text` is kept whole; never paraphrased, never silently corrupted).

    Coordinator follow-up (review of commit 3006e92f): the stderr line alone is easy to miss
    (it never surfaces anywhere a normal `compact` invocation's stdout summary is read) --
    `segmentation_failures`, when given, gets `item_id_base` appended on this same failure
    path so `extract_items`'s caller (`jev_compact.py::cmd_compact`) can fold the count into
    its own one-line summary (`segmentation_failed=N`) instead of the fallback being visible
    only to whoever happens to be watching stderr. `None` (the default) keeps every existing
    caller -- including every test that calls this function directly -- unchanged.
    """
    whole_item = [Item(item_id_base, "tool", f"{name}({tool_input})\n{result_text}",
                        estimate_tokens(f"{name}({tool_input})\n{result_text}"), ts, turn)]
    if estimate_tokens(result_text) <= _SEGMENT_THRESHOLD_TOKENS:
        return whole_item

    try:
        origin = Origin(source="tool", ref=name, turn=turn)
        segs = segment(_detection_view(result_text), origin)
        if len(segs) <= 1:
            return whole_item

        original_lines = result_text.splitlines(keepends=True)
        pieces: list[Item] = []
        for i, seg in enumerate(segs):
            if seg.line_span is None:
                raise AssertionError("segment() returned no line_span for non-empty input")
            a, b = seg.line_span
            piece_text = "".join(original_lines[a - 1:b])
            pieces.append(Item(
                id=f"{item_id_base}@{a}-{b}", kind="tool", text=piece_text,
                tokens=estimate_tokens(piece_text), ts=ts, turn=turn + i,
                protected=seg.kind in _PROTECTED_SEGMENT_KINDS,
            ))
        # segments.py's own docstring: losslessness is "guaranteed structurally... not by
        # care" -- re-checked here anyway because this slices the CALLER's original lines via
        # a detection-view-derived line_span, one layer removed from segment()'s own guarantee
        # (which only covers its own input, the detection view, not what we chose to slice
        # with its cuts).
        if "".join(p.text for p in pieces) != result_text:
            raise AssertionError("segmentation lost or altered bytes -- losslessness violated")
    except Exception as exc:  # noqa: BLE001 (not enabled in this project's ruff config; see
        # the docstring above) -- deliberately broad: ANY segmentation failure, expected or
        # not (a future jevctx.segments bug included), must degrade to the whole item, never
        # take the whole `compact` run down over one tool result.
        print(
            f"jev: segmentation failed for {item_id_base} ({type(exc).__name__}: {exc}) -- "
            "keeping the tool result whole",
            file=sys.stderr,
        )
        if segmentation_failures is not None:
            segmentation_failures.append(item_id_base)
        return whole_item

    return pieces


def _owner_kind(kind: ItemKind, text: str) -> ItemKind:
    """`kind`, except an owner ("user") text that is a bare control word becomes "control"
    (TRDD-DZ1KOGAC's demotion, retargeted by TRDD-D7RLXAN1 -- see `ItemKind`)."""
    return "control" if kind == "user" and transcript_roles.is_control_input(text) else kind


def extract_items(
    transcript_path: str | Path, *, segmentation_failures: list[str],
    window: ConversationWindow | None = None,
    malformed_lines: list[int],
) -> list[Item]:
    """Walk one transcript JSONL and return its extracted, chronologically ordered items.

    `segmentation_failures` is REQUIRED (TRDD-DQXMND59 stage 3, item E -- same reasoning as
    `malformed_lines` below: a prior commit left it optional with a `None` default, and
    `expand --list` was passing none at all, so a segmentation failure on THAT path was skipped
    in total silence). Appended to (in place) with the `item_id_base` of every tool result whose
    segmentation attempt failed and fell back to the pre-card-6 whole item -- see
    `_segment_tool_result`'s own docstring.

    `window`, when given (TRDD-D7RLXAN1), is filled in place with the LAST compact boundary,
    its preserved uuids and its paired summary -- see `ConversationWindow`. Neither the
    boundary line nor the summary entry ever becomes an item.

    `malformed_lines` is REQUIRED (adversarial review, 2026-09-24, finding A): a prior commit
    made it optional and no caller passed it, so a damaged line was skipped in total silence.
    Appended to (in place) with the 1-based line number of every line that could not be parsed
    as a JSON object -- the live-session case: the process writing the transcript can leave
    the LAST line half-written mid-append, any line can carry non-UTF-8 bytes from a
    subprocess's raw output, and a line can parse to valid JSON that is not an object (finding
    D). Such a line is skipped, not swallowed silently: the count is the caller's signal that
    the walk saw damage, mirroring `segmentation_failures`. A caller that genuinely does not
    care still has to write `malformed_lines=[]` -- that one extra word is cheap, "forgot to
    look" is not. See `jsonl_walk.iter_jsonl_entries` (TRDD-DQXMND59 stage 3: moved to its own
    stdlib-only module, see that module's docstring for why), the shared walk this function and
    `jev_expand.read_jsonl_entry` both use.

    KNOWN LIMITATION (adversarial review, 2026-09-24): `errors="replace"` only catches damage
    that ALSO breaks `json.loads` -- a line whose bad bytes decode to U+FFFD but still happens
    to parse as valid JSON is not counted in `malformed_lines`, because nothing downstream of
    the decode can tell "replaced" content from real content. A tool_result that genuinely
    carries non-UTF-8 bytes (a subprocess's raw non-UTF-8 stdout, a binary diff) is silently
    lossy in that one case. Accepted for this fix: the goal is "one bad byte never aborts the
    whole compact run", not "every byte-level anomaly is flagged" -- the latter would need
    per-field validity tracking `json.loads` does not offer.

    A related but SEPARATE anomaly (finding C, same review) is NOT a `malformed_lines` case at
    all: `json.loads` accepts a lone (unpaired) UTF-16 surrogate escape inside a JSON string
    (e.g. a multi-byte emoji Node's writer cut in half, `"\ud83d"` alone) and returns it as a
    normal-looking `str` -- the line parses fine, `malformed_lines` is right to stay silent
    about it. What breaks is every LATER `.encode("utf-8")` on that text (`compose()`'s byte
    budget, in particular): `UnicodeEncodeError`, uncaught. Fixed at `Item.__post_init__`
    (`jsonl_walk.drop_lone_surrogates`), not here -- by the time this function returns, every
    `Item.text` it produced is guaranteed `.encode("utf-8")`-safe. TRDD-DQXMND59 stage 3, item
    A: `expand` (which builds text WITHOUT going through `Item`) must run the same function over
    what it prints, or the exact same crash resurfaces one layer up -- see
    `jev_compact.py::cmd_expand`.

    One pass, top to bottom: a `tool_use` block is remembered by its own `id` as soon as
    it's seen, so the `tool_result` block that answers it (which always appears in a LATER
    line -- the transcript is append-only) can be paired with it by the time we reach it.

    TRDD-RAEGS1D5 (2026-09-23), commit 2353a88a plus the orchestrator's same-day scope
    extension after an adversarial review of it:

    1. A `user`-role record's kind comes from `transcript_roles.classify_record`: role
       "human" -> kind "user"; role "notification"/"peer"/"system" -> kind "event" (still
       extracted, still scorable/inlinable, just never counted as a human message -- see
       `build_digest`); role "skip" (sidechain/compact-summary/meta) -> no item at all.

    2. The heartbeat fire's OWN initiating prompt (`_is_heartbeat_entry`) is still dropped
       outright, as before -- it carries no information, it's always the same fixed text.
       Defect 1 fix (review of 2353a88a): everything ELSE the turn it triggers does is now
       KEPT. Only two patterns are still dropped, matched directly rather than via a
       whole-turn skip window: the dispatcher-stub `tool_use`/`tool_result` pair
       (`_DISPATCHER_STUB_MARKER`), and an assistant text block that is nothing but the bare
       heartbeat-protocol reply (`transcript_roles.is_heartbeat_reply`, TRDD-D7RLXAN1). Real work a
       `[janitor-resume]` turn does -- other tool calls, other results, real prose -- survives.

    3. `type: "attachment"` entries (defect 4): a mid-turn queued owner message or queued
       task-notification (`attachment.type == "queued_command"`) is extracted like a `user`
       entry -- `commandMode: "prompt"` -> kind "user", `commandMode: "task-notification"` ->
       kind "event". Every other `attachment` (`hook_success`, `hook_additional_context`, ...)
       is hook noise and contributes nothing, matching the pre-fix (accidental) behaviour.

    4. An assistant entry with `isApiErrorMessage` is skipped entirely (report §4 glue item
       1) -- a transport-error placeholder, not real assistant output.
    """
    path = Path(transcript_path)
    items: list[Item] = []
    turn = 0
    # tool_use id -> (name, truncated-input-json) remembered for pairing with its result.
    pending_tool_uses: dict[str, tuple[str, str]] = {}
    # tool_use ids identified as the heartbeat's own dispatcher-stub call -- see point 2 above.
    # Membership, not a window: only THIS call and the one tool_result that answers it are
    # dropped, whatever else surrounds them in the same turn.
    quiet_tool_use_ids: set[str] = set()

    # V7 robustness (TRDD-DQXMND59): per-line decode+parse via `jsonl_walk.parse_jsonl_line`
    # (shared with `jsonl_walk.iter_jsonl_entries`, see its docstring) -- one bad byte or one
    # structurally broken line is counted in `malformed_lines` and skipped, never aborting the
    # rest of the walk.
    with path.open("rb") as fh:
        for line_no, raw_line in enumerate(fh, start=1):
            entry = jsonl_walk.parse_jsonl_line(raw_line, line_no, malformed_lines)
            if entry is None:
                continue
            entry_type = entry.get("type")
            # TRDD-D7RLXAN1: a `type: "system"` compact_boundary line is outside
            # `_WALKED_ENTRY_TYPES`, so it must be checked BEFORE that skip. The last one wins
            # (Claude Code's summaries are cumulative). The summary is reset here and paired by
            # anchorUuid below (advisor finding D): a boundary whose summary line never landed
            # (session killed between the two) must not show the PREVIOUS summary as if it
            # covered the gap.
            if (window is not None and entry_type == "system"
                    and entry.get("subtype") == "compact_boundary"
                    and not entry.get("isSidechain")):
                preserved = (entry.get("compactMetadata") or {}).get("preservedMessages") or {}
                window.boundary_turn = turn
                window.preserved_uuids = frozenset(preserved.get("allUuids") or ())
                window.summary = None
                window.pending_anchor = preserved.get("anchorUuid")
                continue
            if entry_type not in _WALKED_ENTRY_TYPES:
                continue
            # A subagent's turns live in the SAME main transcript file (isSidechain: true)
            # but are not the main conversation -- scoring/inlining them into the parent
            # session's compacted context would mix two different tasks' history.
            if entry.get("isSidechain"):
                continue

            uuid = entry.get("uuid")
            ts = entry.get("timestamp")
            content = entry.get("message", {}).get("content")

            if entry_type == "user":
                # TRDD-D7RLXAN1: Claude Code's own compaction summary, kept verbatim as the
                # stand-in for every pre-boundary message. Captured only when it belongs to the
                # pending boundary (its uuid == the boundary's anchorUuid) or no anchor is
                # pending (an older shape, or an orphan summary) -- then skipped as before.
                if window is not None and entry.get("isCompactSummary"):
                    if window.pending_anchor is None or uuid == window.pending_anchor:
                        # TRDD-DQXMND59 stage 3, item G: `window.summary` never passes through
                        # `Item.__post_init__` (it is not an `Item`) so, unlike every scored/
                        # conversation item's `.text`, nothing sanitized a lone surrogate here
                        # until now -- `compose()` writes it straight into the final document.
                        window.summary = jsonl_walk.drop_lone_surrogates(tool_result_text(content))
                    continue
                if _is_heartbeat_entry(entry):
                    continue  # the fire's OWN prompt -- always dropped, see point 2 above

                role = transcript_roles.classify_record(entry)
                if role == "skip":
                    continue  # sidechain (already caught above)/compact-summary/meta
                kind: ItemKind = "user" if role == "human" else "event"

                if isinstance(content, str):
                    # TRDD-DZ1KOGAC: a bare "resume"/"continue"/argument-less "/compact" is
                    # still the owner's own words (role stays "human" -- authorship is true),
                    # but it carries no content, and measured on real transcripts it was
                    # displacing the owner's actual instructions from the owner tier, the
                    # guaranteed newest-owner slot, and the digest. Demote the ITEM KIND only --
                    # to "control" (TRDD-D7RLXAN1), not "event": it stays conversation, never
                    # scored. A non-human record keeps its "event" kind whatever its text.
                    item_kind = _owner_kind(kind, content)
                    items.append(Item(f"{uuid}:0", item_kind, content,
                                       estimate_tokens(content), ts, turn))
                    turn += 1
                elif isinstance(content, list):
                    for idx, block in enumerate(content):
                        if not isinstance(block, dict):
                            continue
                        btype = block.get("type")
                        if btype == "text":
                            text = block.get("text", "")
                            item_kind = _owner_kind(kind, text)
                            items.append(Item(f"{uuid}:{idx}", item_kind, text,
                                               estimate_tokens(text), ts, turn))
                            turn += 1
                        elif btype == "tool_result":
                            tool_use_id = str(block.get("tool_use_id"))
                            if tool_use_id in quiet_tool_use_ids:
                                # The heartbeat's own dispatcher-stub call answering itself --
                                # never an item, see point 2 above.
                                continue
                            # WHY no isMeta guard here: isMeta marks a human-facing pseudo
                            # user message (hook-injected context), never a tool result --
                            # the spec's isMeta clause is scoped to str/list[text] content.
                            name, tool_input = pending_tool_uses.get(
                                tool_use_id, ("<unknown tool>", "")
                            )
                            result_text = tool_result_text(block.get("content"))
                            # Card 6 (TRDD-88DOI824): one or more Items, per
                            # `_segment_tool_result` -- see that function's own docstring.
                            new_items = _segment_tool_result(
                                f"{uuid}:{idx}", name, tool_input, result_text, ts, turn,
                                segmentation_failures=segmentation_failures,
                            )
                            items.extend(new_items)
                            turn += len(new_items)
                # else: no content (or an unrecognised shape) -- nothing to extract.

            elif entry_type == "attachment":
                # Defect 4 (orchestrator scope extension): a mid-turn queued record -- the
                # owner typed while a turn was running, or a task-notification was delivered
                # mid-turn. Every other attachment kind (hook output, ...) is noise.
                # TRDD-DQXMND59 follow-up: the type gate AND the prompt text-join both live in
                # `jev_expand.attachment_item_text` now, the ONE place this rule is allowed to exist (see
                # its own docstring) -- `expand` (`jev_expand.extract_block`) calls the
                # SAME function, so the two can never drift apart again.
                text = attachment_item_text(entry)
                if text is None:
                    continue
                attachment = entry.get("attachment")
                # A `continue` here would be a SILENT skip of a broken invariant: `text is not
                # None` already proves `jev_expand.attachment_item_text` found `attachment` to be a dict
                # (its own only non-None return path) -- this assert exists to satisfy the type
                # checker's narrowing, not to handle a real case, so a failure means the
                # invariant itself broke and must be loud, not swallowed like a normal skip.
                assert isinstance(attachment, dict)
                command_mode = attachment.get("commandMode")
                att_origin = attachment.get("origin")
                att_origin_kind = att_origin.get("kind") if isinstance(att_origin, dict) else None
                # Defect-5 real-data re-derivation caught a bug here: `commandMode ==
                # "prompt"` alone is NOT sufficient for "human" -- measured on the 49 MB
                # transcript, 19 of 23 `commandMode: "prompt"` attachments carry
                # `origin.kind: "peer"` (a cross-session SendMessage from ANOTHER agent,
                # delivered through the SAME mid-turn queue a genuine owner keystroke uses),
                # only 4 carry `origin.kind: "human"`. Only the latter is the owner's own words.
                if command_mode == "prompt" and att_origin_kind == "human":
                    att_kind: ItemKind = "user"
                elif command_mode in ("prompt", "task-notification"):
                    att_kind = "event"  # a peer/cross-session message, or a queued notification
                else:
                    continue  # an attachment.commandMode never measured -- skip, don't guess
                # TRDD-DZ1KOGAC: same demotion as the main "user" branch above -- a mid-turn
                # queued bare control word is still the owner's words, never content
                # ("control", TRDD-D7RLXAN1).
                att_kind = _owner_kind(att_kind, text)
                items.append(Item(f"{uuid}:0", att_kind, text, estimate_tokens(text), ts, turn))
                turn += 1

            else:  # entry_type == "assistant"
                if entry.get("isApiErrorMessage"):
                    continue  # a transport-error placeholder, not real assistant output
                if not isinstance(content, list):
                    continue
                for idx, block in enumerate(content):
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type")
                    if btype == "thinking":
                        continue  # never an item, never remembered
                    if btype == "text":
                        text = block.get("text", "")
                        # TRDD-D7RLXAN1 / TRDD-IYNS7H83: only the BARE quiet reply is dropped
                        # (`transcript_roles.is_heartbeat_reply`, the one shared predicate). A
                        # reply carrying drift lines is content -- 9 such replies on b2bf5b7b
                        # ("The live account is ...") once vanished from the full copy.
                        if transcript_roles.is_heartbeat_reply(text):
                            continue  # bare heartbeat-protocol reply -- see point 2 above
                        items.append(Item(f"{uuid}:{idx}", "assistant", text,
                                           estimate_tokens(text), ts, turn))
                        turn += 1
                    elif btype == "tool_use":
                        raw_input = json.dumps(block.get("input", {}), sort_keys=True)
                        tool_id = str(block.get("id"))
                        pending_tool_uses[tool_id] = (
                            block.get("name", "<unnamed tool>"),
                            _truncate(raw_input, _TOOL_INPUT_TRUNCATE),
                        )
                        if _DISPATCHER_STUB_MARKER in raw_input:
                            quiet_tool_use_ids.add(tool_id)
                    # any other block type: skip, not remembered

    return items


def build_digest(
    items: list[Item], trdd_state_heads: list[str], cap_tokens: int = 4000
) -> str:
    """The small task description scored items are judged against.

    Order: STATE heads first (the durable, machine-produced facts), then the last three
    human messages and the last two assistant `text` blocks, chronological -- so that
    if the cap forces dropping whole parts, the least essential piece (an OLDER state head)
    goes first and the freshest words survive longest. The last two assistant messages are
    included alongside the human ones (not just the human ones alone) because on an
    unattended session the last HUMAN message can be old -- what the agent last said it was
    doing anchors relevance-scoring better than a stale human prompt alone would.

    `kind == "user"` here means genuinely human (TRDD-RAEGS1D5, 2026-09-23 bug fix): before
    it, `extract_items` gave that kind to every non-`isMeta` user-role text, so a task
    notification (a subagent's report, re-classified kind "event" now) could crowd out the
    real "last three human messages" this function's own name promises -- measured on a real
    transcript, 26 of 36 "user" items were task notifications. `it.kind == "user"` needs no
    change here after the orchestrator's scope-extension rework either: `extract_items` now
    only ever hands out that kind for a `transcript_roles.classify_record` role of "human"
    (a `type: "user"` entry) or an `attachment.commandMode == "prompt"` mid-turn queued owner
    message (defect 4) -- both are genuinely human, so this filter stays correct by construction.
    """
    user_items = [it for it in items if it.kind == "user"]
    assistant_items = [it for it in items if it.kind == "assistant"]
    recent = sorted(user_items[-3:] + assistant_items[-2:], key=lambda it: it.turn)

    parts: list[str] = [
        "\n".join(head.splitlines()[:30]) for head in trdd_state_heads
    ] + [it.text for it in recent]

    if not recent and not trdd_state_heads:
        raise NoDigest("no human message and no TRDD STATE head -- nothing to digest")

    # Drop whole parts from the front (the lowest-priority end, per the ordering above)
    # until the joined digest fits the cap. A part that alone exceeds the cap is itself
    # truncated rather than dropped, so a non-empty digest never collapses to nothing.
    while parts and estimate_tokens("\n\n".join(parts)) > cap_tokens:
        if len(parts) == 1:
            # Binary-shrink the last remaining part until it fits.
            part = parts[0]
            while part and estimate_tokens(part) > cap_tokens:
                part = part[: max(1, len(part) // 2)]
            parts[0] = part
            break
        parts.pop(0)

    return "\n\n".join(parts)


def _score_batch(
    batch: Batch,
    *,
    items_by_id: dict[str, Item],
    digest: str,
    client: JevClient,
    relevance_threshold: float,
) -> dict[str, Scores]:
    """Score one batch; the unit `score_items` fans out over a `ThreadPoolExecutor` (card 3,
    TRDD-CC0CZLMO) -- pulled out of the batch loop so each batch's `client.ask()` round trip
    can run on its own worker thread. `items_by_id`/`digest`/`client`/the threshold are
    read-only for the whole `score_items` call, so sharing them across threads needs no lock.

    TRDD-R9UXOSR5: relevance only. The old per-kind split (card 5, TRDD-HWF3QFAB) asked a
    second DECISION question of "user" batches; D7RLXAN1 already stopped any "user" item
    reaching `score_items` (see `split_conversation`), so the question and its threshold went
    with it -- every scored item is tool/event and judged on relevance alone.
    """
    if batch.meta.get("oversized"):
        # Never sent -- fail-open at the library level regardless of caller intent, exactly
        # like jevctx.scorer's own oversized handling. `compose` still refuses to inline it
        # because `oversized=True` here (spec: "never inlined").
        it = items_by_id[batch.items[0].id]
        return {it.id: Scores(relevance=1.0, oversized=True, kept=False)}

    refs = batch.question_keys
    state = _scorer.build_state(digest, batch.items, refs)
    questions: dict[str, Question] = {
        f"{ref}:rel": _scorer._ref_question(RETRIEVE_QUESTION, ref) for ref in refs
    }

    answers = client.ask(state, questions)  # a JevError here propagates -- see score_items

    result: dict[str, Scores] = {}
    for ref, lib_item in zip(refs, batch.items, strict=True):
        it = items_by_id[lib_item.id]
        rel_answer = answers.get(f"{ref}:rel")
        if not isinstance(rel_answer, NoulAnswer):
            raise JevValidationError(
                f"expected a NoulAnswer for ref {ref!r}, got {type(rel_answer).__name__}"
            )
        rel = rel_answer.value
        kept = rel >= relevance_threshold
        result[it.id] = Scores(relevance=rel, oversized=False, kept=kept)
    return result


def _halve(batch: Batch) -> tuple[Batch, Batch]:
    """Split `batch` into two order-preserving halves, each with its own `i0..iN-1` refs.

    Never re-runs `BudgetPlanner`: both halves are strict subsets of a batch that already
    fit under every cap, so they fit too -- no re-planning needed, just fewer items sharing
    the same relative ref numbering `_score_batch` already expects.
    """
    mid = len(batch.items) // 2
    left, right = batch.items[:mid], batch.items[mid:]
    return (
        Batch(items=left, question_keys=[f"i{i}" for i in range(len(left))]),
        Batch(items=right, question_keys=[f"i{i}" for i in range(len(right))]),
    )


def _score_batch_resilient(
    batch: Batch,
    *,
    items_by_id: dict[str, Item],
    digest: str,
    client: JevClient,
    relevance_threshold: float,
    retry_budget: _RetryBudget,
    origin_index: int,
    max_split_depth: int,
    depth: int = 0,
) -> tuple[dict[str, Scores], list[str]]:
    """`_score_batch`, but a `JevBlockedError` or a `max_tokens_exceeded` `JevValidationError`
    splits the batch in half and retries the halves instead of aborting the whole
    `score_items` call (TRDD-1ETALGDG).

    Recurses SERIALLY within this one worker thread -- never through `score_items`'s
    `ThreadPoolExecutor` -- so a block/oversize storm never compounds into MORE concurrent
    requests against whatever tripped it ("no fan-out of blocked siblings", the card's own
    wording). Each half's retry costs one unit of `retry_budget` (the ORIGINAL per-batch
    attempt from `score_items`'s own work list is never charged, only a split-triggered
    retry is).

    TRDD-1ETALGDG followup: when the budget is spent, that HALF's items become pointers
    directly -- terminal, exactly like hitting `max_split_depth` -- instead of raising. The
    ORIGINAL behaviour (re-raise immediately) propagated out through `score_items`'s
    `ThreadPoolExecutor` fail-closed handling and aborted every OTHER batch's scoring too,
    just because ONE batch happened to exhaust a budget shared across the whole call --
    turning a single poison batch into a total compaction failure, exactly what splitting
    was supposed to prevent. `score_items`'s own post-loop check (more than half of ALL
    items ended up unscored) is what still turns a sufficiently broken backend into a
    whole-call failure.

    Returns `(scores, blocked_ids)`: `blocked_ids` names every item that was still
    unscoreable even alone, once `max_split_depth` (or a single-item batch) was reached --
    `score_items` turns each into a pointer-only entry and prints one finding line per item,
    never a raise, UNLESS every batch in the whole call ends up blocked (checked once, in
    `score_items`, after every batch has finished).
    """
    try:
        return (
            _score_batch(
                batch, items_by_id=items_by_id, digest=digest,
                client=client, relevance_threshold=relevance_threshold,
            ),
            [],
        )
    except (JevBlockedError, JevValidationError) as exc:
        is_retryable = isinstance(exc, JevBlockedError) or _is_max_tokens_exceeded(exc)
        if not is_retryable:
            raise  # a non-max_tokens_exceeded JevValidationError is a request-shape bug --
            # splitting the batch cannot fix a malformed request, so this propagates exactly
            # like it did before this card (JevValidationError.__doc__: "never retried").

        if len(batch.items) <= 1 or depth >= max_split_depth:
            # Terminal: never scored, never inlined (verbatim guarantee -- the item's own
            # text is never touched, it just never reaches Jev again). One finding line per
            # item, carrying exactly the step-1 bisection facts the card asked for: which
            # origin batch, how many split levels, the item id, and -- for a block -- the
            # response's own cf-ray/body-hash (never the body itself).
            detail = ""
            if isinstance(exc, JevBlockedError):
                detail = f" cf_ray={exc.cf_ray} body_sha256={exc.body_sha256[:16]}"
            for it in batch.items:
                print(
                    f"jev: item {it.id} never scored (origin_batch={origin_index} "
                    f"depth={depth} {type(exc).__name__}{detail}) -- inlined as a pointer",
                    file=sys.stderr,
                )
            return {}, [it.id for it in batch.items]

        left, right = _halve(batch)
        merged: dict[str, Scores] = {}
        blocked: list[str] = []
        detail = ""
        if isinstance(exc, JevBlockedError):
            detail = f" cf_ray={exc.cf_ray} body_sha256={exc.body_sha256[:16]}"
        for half in (left, right):
            if not retry_budget.take():
                # TRDD-1ETALGDG followup: cap exhausted -- terminal for this half (see the
                # docstring: this must NOT raise, or one batch's exhausted budget aborts
                # every other batch too). Same finding-line shape as the max-depth terminal
                # case above, "retry_budget_exhausted" in place of the depth/leaf reason.
                for it in half.items:
                    print(
                        f"jev: item {it.id} never scored (origin_batch={origin_index} "
                        f"depth={depth + 1} retry_budget_exhausted {type(exc).__name__}"
                        f"{detail}) -- inlined as a pointer",
                        file=sys.stderr,
                    )
                blocked.extend(it.id for it in half.items)
                continue
            half_scores, half_blocked = _score_batch_resilient(
                half, items_by_id=items_by_id, digest=digest,
                client=client, relevance_threshold=relevance_threshold,
                retry_budget=retry_budget,
                origin_index=origin_index, max_split_depth=max_split_depth, depth=depth + 1,
            )
            merged.update(half_scores)
            blocked.extend(half_blocked)
        return merged, blocked


def score_items(
    items: list[Item],
    digest: str,
    client: JevClient,
    *,
    relevance_threshold: float = DEFAULT_RELEVANCE_THRESHOLD,
    max_workers: int = 8,
    max_split_depth: int = _MAX_SPLIT_DEPTH,
    max_retried_requests: int = _MAX_RETRIED_REQUESTS,
) -> dict[str, Scores]:
    """Score every item against the relevance question, batched and fanned out concurrently.

    TRDD-R9UXOSR5: relevance only, one question per item. The old second DECISION question
    (card 3 of the spec, card 5's per-kind batching) retired with the `kind == "user"` group
    D7RLXAN1 already removed from `score_items`'s input (`split_conversation` routes every
    owner/assistant/control item to the verbatim conversation, never scored) -- so the batch
    plan is one homogeneous group of tool/event items, `_BATCH_MAX_QUESTIONS` (== 32) items
    per batch, one real question each. This still drives `BudgetPlanner` + `client.ask()`
    directly via `_score_batch` (not `jevctx.scorer.score_items`), for the fail-closed and
    resilience behaviour below.

    Card 3 (TRDD-CC0CZLMO): batches are planned once, then run concurrently on a
    `ThreadPoolExecutor(max_workers)` -- mirrors `jevctx.scorer.score_items`'s own fan-out
    (scorer.py:149-154), which a serial `for batch in batches` loop here used to leave
    unused; a 49 MB / 7075-item real transcript measured 168s serial on HEAD, over both the
    60s sync and the 120s (then-)detached compaction-lane timeouts. FAIL-CLOSED, unlike the
    library's own default (never fails open like `jevctx.scorer.score_items`'s
    `on_error="keep"`): the first `JevError` -- raised inside a worker thread, surfaced by
    `future.result()` -- cancels every batch that has not started yet (`future.cancel()`; a
    batch already mid-flight on another worker thread cannot be interrupted, only prevented
    from ever starting) and propagates. The one caller (`scripts/jev_compact.py compact`)
    must fall back to the fact-only template on any Jev error, never silently keep
    everything. DETERMINISTIC regardless of `max_workers`: batch membership is decided by
    `BudgetPlanner.plan` up front (never by execution order), and results are merged into
    `scores`, a dict keyed by item id, so the ORDER batches finish in cannot change the
    final content -- only how fast it arrives.

    TRDD-1ETALGDG: each batch now runs through `_score_batch_resilient` instead of
    `_score_batch` directly -- a `JevBlockedError` (a Cloudflare edge block, see
    `jevctx.openrouter`) or a `max_tokens_exceeded` `JevValidationError` splits that ONE
    batch and retries the halves (bounded by `max_split_depth`/`max_retried_requests`)
    rather than aborting the whole call the way every other `JevError` still does. An item
    that is still unscoreable once split all the way down, OR that lost the race for the
    shared `max_retried_requests` budget, becomes a pointer-only `Scores` entry (`kept=False,
    oversized=False, blocked=True` -- rendered by `compose()` with its own "unscored
    (provider firewall)" note, see that function's docstring; the verbatim guarantee still
    holds because a never-scored item's text is never sent again, let alone altered) instead
    of failing the whole compaction -- UNLESS MORE THAN HALF of all items end up unscored
    this way (followup fix: the original "unless literally everything is blocked" gate let
    an almost-all-pointers result through as a "success"), which raises `JevBlockedError`
    (not enough was actually compacted for the result to be useful, so this must count as a
    Jev failure and let the caller fall back, not silently emit a mostly-pointers document
    as if it succeeded).
    """
    if not items:
        return {}

    items_by_id = {it.id: it for it in items}

    rel_tokens = estimate_tokens(_scorer._ref_question(RETRIEVE_QUESTION, "i0").to_payload())
    envelope_tokens = estimate_tokens(_scorer.build_state(digest, [], []))

    score_items_list = [ScoreItem(id=it.id, text=it.text, tokens=it.tokens) for it in items]
    batches = BudgetPlanner(
        max_questions=_BATCH_MAX_QUESTIONS,
        state_plus_all_questions=_SAFE_STATE_PLUS_ALL_QUESTIONS_TOKENS,
    ).plan(score_items_list, rel_tokens, envelope_tokens)

    scores: dict[str, Scores] = {}
    blocked_ids: list[str] = []
    retry_budget = _RetryBudget(max_retried_requests)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [
            pool.submit(
                _score_batch_resilient, batch,
                items_by_id=items_by_id, digest=digest, client=client,
                relevance_threshold=relevance_threshold,
                retry_budget=retry_budget, origin_index=origin_index,
                max_split_depth=max_split_depth,
            )
            for origin_index, batch in enumerate(batches)
        ]
        try:
            for future in as_completed(futures):
                batch_scores, batch_blocked = future.result()
                scores.update(batch_scores)
                blocked_ids.extend(batch_blocked)
        except BaseException:
            # Fail-closed (see docstring): stop every batch that hasn't started yet. A batch
            # already running on another worker thread can't be interrupted -- `.cancel()`
            # on it is a documented no-op (returns False) -- so this only shrinks how much
            # MORE work happens after the first failure; the `with` block above still waits
            # for whatever was already in flight before this exception leaves the function.
            for f in futures:
                f.cancel()
            raise

    # TRDD-1ETALGDG followup: raise iff MORE THAN HALF of all items ended up unscored, not
    # only when literally nothing was scored (see the docstring) -- a document that is
    # almost all "expand this yourself" pointers has effectively lost the compaction even
    # though `scores` is technically non-empty.
    if blocked_ids and len(blocked_ids) * 2 > len(items):
        raise JevBlockedError(
            f"too many items blocked or oversized ({len(blocked_ids)}/{len(items)}); "
            "not enough could be scored to be useful"
        )
    for item_id in blocked_ids:
        # Never scored, never inlined -- see docstring's verbatim-guarantee note. `blocked`
        # marks these apart from an ordinary below-threshold item so `jev_compact.py` can
        # count them for its own `blocked=N` visibility line and `compose()` can render a
        # distinct pointer note (see their own docstrings).
        scores[item_id] = Scores(relevance=0.0, oversized=False, kept=False, blocked=True)
    return scores


def _format_pointer(item: Item) -> str:
    """The elided-item stand-in text, via `jevctx.pipeline.format_pointer` (card 5,
    TRDD-HWF3QFAB). The local literal this replaced had no escaping -- a `"` or `\\` in an
    item's first line produced a pointer `pipeline.parse_pointer`/`find_pointers` could not
    parse back -- and previewed the literal first line even when it was blank; the summary
    below is the first NON-EMPTY line instead, truncated the same way as before. WHY no path
    either: a pointer must never hand the model something it could `Read` -- the transcript is
    24-258 MB (docs_dev/jev-compaction-spec.md card 3) -- so the path lives once, in the
    header, never per pointer.

    `lines=None` always, EVEN for a segment Item (card 6, TRDD-88DOI824): this superseded an
    earlier note here that said the `lines=a-b` field `format_pointer` supports would carry a
    segment's span -- it does not, on purpose. A segment's span lives INSIDE `item.id` instead
    (`<uuid>:<n>@<a>-<b>`, see `_segment_tool_result`), because the whole point is a SINGLE
    copy-pasteable token for `expand <id>`: rendering `id=<uuid>:<n> lines=a-b` would let the
    model copy just the `id=` value, and `jev_compact.py expand <uuid>:<n>` (no `@`) returns
    the WHOLE block, silently wrong for a pointer meant to name one segment.

    Adversarial-review disclosure (TRDD-88DOI824, not fixed): this makes a segment's pointer
    line UNPARSEABLE by `pipeline.parse_pointer`/`find_pointers` -- their `_POINTER_RE`'s id
    character class (`[A-Za-z0-9:_.-]+`) does not include `@`, so the regex fails to match at
    that position and `find_pointers` silently skips the whole line. Same trade-off this
    module already made for the retired `_format_decision_pointer` (TRDD-R9UXOSR5 removed it
    with the decision question) --
    not fixed here for the same reason: nothing in this project reads `compose()`'s FULL or
    injected output back through `find_pointers`/`parse_pointer` in production today (`grep`
    confirmed: only `jevctx.pipeline` itself and this repo's own pointer-format tests call
    them), so the round-trip guarantee that breaks is currently dormant, not live -- but it IS
    a real, silent gap for a future consumer who assumes every `[[elided ...]]` line
    round-trips, and is disclosed here rather than left to be rediscovered.
    """
    summary = ""
    for line in item.text.splitlines():
        if line.strip():
            summary = _truncate(line, _POINTER_PREVIEW_CHARS)
            break
    return format_pointer(Pointer(id=item.id, lines=None, tokens=item.tokens, summary=summary))


# Spec: "Oversized single item (jev marks oversized) -> never inlined; pointer + first 20
# lines" -- a DIFFERENT, richer pointer than a plain budget-dropped item gets (that one is
# just the single-line `_format_pointer` above). An oversized item never even reached Jev
# (jevctx's own budget planner refuses to send it -- see `score_items`), so it has no
# relevance signal at all; the extra 20 lines give the model enough to decide
# whether `expand` is worth it, which the 80-char preview alone cannot.
_OVERSIZED_PREVIEW_LINES = 20


def _oversized_preview(item: Item) -> str:
    return "\n".join(item.text.splitlines()[:_OVERSIZED_PREVIEW_LINES])


# TRDD-RAEGS1D5 (compose() budget floor round 5, coordinator ruling on the round 4 regression
# report): round 4's literal "non-owner items, then non-guaranteed-owner items" backstop order
# could empty the non-owner tier ENTIRELY before touching a single non-guaranteed-owner item --
# measured on real data, this dropped non-owner items in the final injected copy from 4/6/4
# (aabd8b0c, "jev newest+3") to 0/0/3 on three real transcripts. Owner ruling: "the at-least-3
# non-owner target stands; its purpose is that the resumed session learns what was DONE" -- so
# stage (2) below stops SHORT of this floor, deferring the harder choice (non-guaranteed-owner
# items, stage (3)) first, and only comes back for the last `_NON_OWNER_FLOOR` non-owner items
# (stage (4)) once stage (3) alone was not enough. See compose()'s own docstring for the full
# stage list. The injected copy meets the same floor at admission instead, by reserving it
# before the owner tier (`_select_injected` step 2).
_NON_OWNER_FLOOR = 3

# Card 5 content-fit measured fact (reports/compaction-replacement/): the appended note for a
# digest truncated by compose()'s max_bytes backstop -- see compose()'s own docstring.
_DIGEST_TRUNCATED_NOTE = "\n\n[[digest truncated to fit the handoff budget]]"


# TRDD-RAEGS1D5 (compose() budget floor round 3 -- coordinator review of round 2,
# reports/compaction-replacement/20260924_013141+0200-jev-inject-room-floor-round2.md finding
# 2): `render()`'s own fixed lines (header, section headings, the trailing "pointers expand
# with" line) embed `transcript_path` (TRDD-EFA4P42B: once, in the trailer -- it used to be up
# to four times) and `full_context_path` once -- neither name appears here, on purpose, so this
# marker's byte cost is CONSTANT regardless of how long either path is. See
# `_render_minimal_fallback`, compose()'s last-resort stage below.
_MINIMAL_FIXED_LINE = "(budget too small, see full copy)"


# Card 5 measured fact (docs_dev/jev-compaction-spec.md card 5 / reports/compaction-replacement/
# 20260923_064108+0200-hook-output-experiments.md): the largest real transcript elides ~18,041
# items -- one pointer line per elided item made `compose()` itself emit ~2.4 MB, independent of
# `budget_tokens` (that budget only bounds KEPT items). Cap the pointer list so its size no longer
# scales with transcript size; the items dropped from the list are still `expand`-able by id, the
# model just is not told about them by name.
#
# TRDD-R9UXOSR5: this cap governs EVERY elided item in the FULL (`--out`) render again. The
# old decision-pointer uncap (TRDD-RAEGS1D5) exempted decision-passing items from it; that
# tier went with the decision question, so there is no second pointer class to exempt.
_MAX_ELIDED_POINTERS = 40

# TRDD-RAEGS1D5 (injected-copy content fix): measured on three real transcripts (reports/
# compaction-replacement/), the injected copy `jev_compact.py compact --inject-out` writes came
# out with 3, 0 and 0 kept items respectively at `--inject-max-bytes 5000` -- the byte backstop
# below used to evict whole kept items until the doc fit, and a real item is routinely bigger
# than the whole injected budget. `compose()`'s caller passes this as `max_item_bytes` ONLY for
# the injected render (never for `--out`, which stays unbounded per item); a kept item over this
# cap is shown as a verbatim prefix (never paraphrased) plus a pointer to the rest, so a handful
# of large items can no longer starve the injected copy down to zero. This is the GENERAL
# per-item cap -- the one exception is the single newest owner message, see
# `NEWEST_OWNER_ITEM_BYTES` below. A TOOL item over its cap is never shown as a prefix at all,
# only as a pointer (TRDD-BLGZTHQ9, see `_select_injected`).
DEFAULT_INJECT_ITEM_BYTES = 700

# TRDD-RAEGS1D5 (jev newest+3, coordinator task 2026-09-24): measured on three real
# transcripts (d30bf250 49 MB, 4eb7bf5d 258 MB, 06f2b2be 4.7 MB) through the ACTUAL hook path
# (`compose_handoff_room` -> the real `jev_compact.py compact` (scoring paid once, reused for
# every candidate value below -- `compose()` is pure) -> `compose_handoff`): the injected
# copy's real room is ~5.5-6.7 KB, and at the flat `DEFAULT_INJECT_ITEM_BYTES` (700) -- every
# kept item, owner and non-owner alike, competing for the same per-item cap -- only 3/3/2
# non-owner items (assistant replies, tool calls, task-notification events -- what the session
# actually DID) survived per render; the target is at least 3 on EVERY real transcript. A
# sweep of `non_owner_item_bytes` from 700 down to 150 (in the full-copy-plus-inject-doc
# rendering, at zero extra network cost -- the same cached scores every time) showed 500 down
# to 375 clear the target with 06f2b2be right at the floor (exactly 3); 350 clears it with a
# real margin on all three (4/6/4) while still keeping the final hook stdout well under the
# ~9,000-byte real ceiling (max observed 7,888 B) and introducing zero slicing on any of the
# three. `compose()`'s `non_owner_item_bytes` param, when given, caps ONLY non-owner items in
# a byte-capped (`max_item_bytes is not None`) render -- owner items (guaranteed or not) keep
# their existing caps (`NEWEST_OWNER_ITEM_BYTES`/`DEFAULT_INJECT_ITEM_BYTES`) unchanged, and
# `--out` (`max_item_bytes` is `None` there) is unaffected either way. Full sweep table:
# reports/compaction-replacement/ (this task's own report).
DEFAULT_INJECT_NON_OWNER_ITEM_BYTES = 350

# TRDD-RAEGS1D5 (orchestrator rebalance, 2026-09-23): the single NEWEST owner (human) message
# is worth more verbatim room than any other item -- it is what the resumed session is most
# likely to need untruncated -- so it gets its OWN, larger cap instead of `max_item_bytes`,
# shown in full when it fits, a verbatim prefix when it doesn't. Every other kept item,
# including every OTHER owner message, still uses `max_item_bytes`.
NEWEST_OWNER_ITEM_BYTES = 1500

# TRDD-RAEGS1D5: pointers are breadcrumbs (an id + an 80-char preview), not the content the
# resumed session actually needs -- capping their share of the injected byte budget keeps them
# from crowding out kept items the way the old whole-item eviction let them. 0.15, under the
# "at most 20-25%" ceiling from the card 5 content-fit review: real-data measurement showed the
# FIXED trailer lines this function always emits (header, the "N more items" line, the "Full
# compacted context" trailer -- the transcript path repeated up to 4x) already consume 1.3-1.6
# KB of a 5000-byte budget before a single pointer or kept item is rendered, so reserving the
# full 20-25% for pointers on TOP of that left too little for kept items; 0.15 is still a real
# ceiling on pointers, sized to what real data showed was actually left once the fixed
# cost is measured (`_select_injected`'s `available` measures that cost directly, never guesses
# it). TRDD-R9UXOSR5: the decision-pointer reserve that used to sit on top of this share
# (`_INJECT_DECISION_POINTER_SHARE`, TRDD-U6C3YXEL) went with the decision question.
_INJECT_POINTER_SHARE = 0.15

# TRDD-BLGZTHQ9 (decision D3, amendment S3): "not truncated" is not "informative" -- measured
# on the three real injected copies, whole-but-empty non-owner items won inline slots on
# relevance alone: `resume` events (6 body chars), a two-line heading `57 ## The open work`
# (17). A non-owner item whose rendered body has fewer non-whitespace, non-tag characters than
# this is neither inlined nor pointed at (a content-free pointer is content-free too); it is
# counted. A WHOLE tool result gets the lower bar below instead, so a short but complete fact
# (a test summary, a `git log -1` line) survives. Owner items are never gated: the owner's
# words are the owner's words.
_INJECT_MIN_BODY_CHARS = 80
_INJECT_MIN_WHOLE_TOOL_BODY_CHARS = 20

# TRDD-D7RLXAN1: the injected copy's share, of the room left after its fixed lines, for the
# newest owner/assistant messages (verbatim, never scored) -- the READ FIRST line included. The
# other 40% keeps room for Jev's tool/event items, the `_NON_OWNER_FLOOR` (3) of them at ~400 B
# each (advisor arithmetic, reports/compaction-replacement/20260924_140604+0200-advisor-prose-
# verbatim.md §3). A starting value; the acceptance run on the cached real sessions checks it.
_INJECT_EXCHANGE_SHARE = 0.60
_EXCHANGES_HEADING = "## Newest messages since the last compaction (verbatim, never scored)"
_CONVERSATION_HEADING = "## Conversation since the last compaction (verbatim, never scored)"
_SUMMARY_HEADING = "### Claude Code's own compaction summary (verbatim)"


def _truncate_prefix_bytes(text: str, limit: int) -> str:
    """A VERBATIM prefix of `text`, at most `limit` UTF-8 bytes -- never paraphrased.

    Cuts at the last newline within the limit when one exists, so a truncated item still
    reads as whole lines; falls back to a raw UTF-8-safe byte cut (via `errors="ignore"`,
    which drops only a codepoint split in half at the boundary, never a whole line) when the
    first line alone exceeds `limit`. TRDD-RAEGS1D5: this is what lets a kept item LARGER than
    the entire injected budget still appear as real transcript bytes instead of being evicted
    whole (see `DEFAULT_INJECT_ITEM_BYTES`'s docstring above).
    """
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    cut = encoded[:limit]
    nl = cut.rfind(b"\n")
    if nl > 0:
        return cut[:nl].decode("utf-8")
    return cut.decode("utf-8", "ignore")


def _render_minimal_fallback(newest_owner: Item | None, max_bytes: int) -> str:
    """The absolute last-resort render (TRDD-RAEGS1D5, compose() budget floor round 3): reached
    only when every earlier degrade step in `compose()` (evict kept items, drop pointers,
    truncate the digest) still leaves `render()`'s own FIXED lines over `max_bytes` -- a small
    `max_bytes` or a long `transcript_path` can overflow that skeleton alone even with nothing
    else left to drop (see `_MINIMAL_FIXED_LINE`'s own comment for the round-2 finding this
    closes). `_MINIMAL_FIXED_LINE` names no path, so its cost never scales with transcript size;
    what follows it is the newest owner message, truncated to whatever room remains, plus a
    pointer to its id (`_format_pointer` -- also path-free) -- the one thing "never sliced"
    still has left to show once every other lever is spent.

    Never exceeds `max_bytes`: `""` when even the marker line alone does not fit, the marker
    alone when a pointer/body would not, the marker plus a truncated body plus its pointer
    otherwise. The final length is re-measured, not trusted from the arithmetic that derives
    `room` -- round 1 and round 2 (see the report cited above) both got exactly that arithmetic
    wrong once already, which is the whole reason this function exists.

    Adversarial-review disclosure (round 3): `newest_owner` is rendered as-is, including when
    it is `blocked` (never sent to Jev, see `Scores.blocked`) -- its `.text` is still the real,
    intact transcript bytes either way, and this function has no scoring-based content
    requirement, so there is nothing to special-case.
    """
    fixed_bytes = len(_MINIMAL_FIXED_LINE.encode("utf-8"))
    if fixed_bytes > max_bytes:
        return ""
    doc = _MINIMAL_FIXED_LINE
    if newest_owner is not None:
        pointer = _format_pointer(newest_owner)
        # -1 -1 for the two "\n" separators between the fixed line, the body and the pointer.
        room = max_bytes - fixed_bytes - 1 - len(pointer.encode("utf-8")) - 1
        if room >= 0:
            body = _truncate_prefix_bytes(newest_owner.text, room)
            doc = f"{_MINIMAL_FIXED_LINE}\n{body}\n{pointer}"
    if len(doc.encode("utf-8")) > max_bytes:
        doc = _MINIMAL_FIXED_LINE if fixed_bytes <= max_bytes else ""
    return doc


def _exchange_block(it: Item, cap: int | None) -> str:
    """One conversation message as rendered by `compose()` (TRDD-D7RLXAN1): its header, then
    its text whole, or -- over `cap` bytes -- a verbatim prefix plus a pointer to the rest.
    A "control" input is labelled "user" (advisor §3): the kind is internal classification,
    the words are the owner's."""
    label = "user" if it.kind == "control" else it.kind
    if cap is None or len(it.text.encode("utf-8")) <= cap:
        return f"-- {label} {it.id} --\n{it.text}"
    return f"-- {label} {it.id} --\n{_truncate_prefix_bytes(it.text, cap)}\n{_format_pointer(it)}"


def _read_first_line(path: str, total: int, shown: int) -> str:
    """TRDD-D7RLXAN1: the injected copy's first line -- the way to every message it could not
    show. An instruction, deliberately (owner Q1, 2026-09-24: the one-time read is accepted)."""
    return (f"READ FIRST: {path} holds every message since the last compaction verbatim "
            f"({total} messages; {shown} shown below). Read it in full before acting; it may "
            "take several Reads (offset/limit).")


def _select_exchanges(conversation: list[Item], budget: int | None) -> tuple[list[str], int]:
    """The injected copy's newest exchanges (TRDD-D7RLXAN1), chronological, within `budget`
    bytes (None = unbounded): (1) the newest OWNER message, capped at `NEWEST_OWNER_ITEM_BYTES`
    or shrunk to what the budget holds; (2) a CONTIGUOUS run backward from the newest message,
    each capped at `DEFAULT_INJECT_ITEM_BYTES`, stopping at the first that does not fit or at
    the owner message -- and when it reaches the owner message, on past it into older messages
    while they fit; (3) a marker counting the messages between the two. Contiguous, not
    skip-and-continue: a hole inside an exchange reads as a conversation that never happened;
    the one exception is the surplus heartbeat status replies of a run (beyond the newest
    `transcript_roles.MAX_CONSECUTIVE_HEARTBEAT_STATUS`), which carry no exchange content and
    stay in the full copy.
    Returns `(blocks, shown)`: each block costs its UTF-8 length plus the one "\\n" `render()`
    joins it with; `shown` counts the messages among them (markers excluded)."""
    def cost(block: str) -> int:
        return len(block.encode("utf-8")) + 1

    def fits(used: int, c: int) -> bool:
        return budget is None or used + c <= budget

    # TRDD-U119W52S: a run of 5-minute heartbeat status replies would otherwise spend the whole
    # budget and stop the contiguous run before the real work behind it.
    # TRDD-FU8MZ0SL: identical heartbeat-led drift/alert replies are capped the same way (shared run key).
    visible = {id(it) for it in transcript_roles.cap_status_runs(
        conversation,
        lambda it: transcript_roles.heartbeat_run_key(it.text) if it.kind == "assistant" else None)}
    used = 0
    owner_idx = next((i for i in range(len(conversation) - 1, -1, -1)
                      if conversation[i].kind == "user"), None)
    owner_block = ""
    if owner_idx is not None:
        owner = conversation[owner_idx]
        owner_block = _exchange_block(owner, NEWEST_OWNER_ITEM_BYTES)
        # The gap marker is charged at its widest up front, so the run below cannot overrun.
        marker_reserve = cost(f"[{len(conversation)} messages between these are only in the "
                              "full copy]")
        if budget is not None and not fits(used, cost(owner_block) + marker_reserve):
            overhead = cost(f"-- user {owner.id} --\n\n{_format_pointer(owner)}") + marker_reserve
            owner_block = (_exchange_block(owner, budget - overhead)
                           if budget - overhead > 0 else "")
        if owner_block:
            used += cost(owner_block) + marker_reserve
    stop = owner_idx if owner_block and owner_idx is not None else -1

    def run_back(start: int, stop_at: int) -> tuple[list[str], int, int]:
        """Blocks from `start` backward while they fit, newest first; the first index NOT
        shown (== `stop_at` when every message down to it was); and the number of surplus
        status replies skipped on the way."""
        nonlocal used
        out: list[str] = []
        i = start
        skipped = 0
        while i > stop_at:
            if id(conversation[i]) not in visible:
                i -= 1  # surplus status reply: no block, no cost
                skipped += 1
                continue
            block = _exchange_block(conversation[i], DEFAULT_INJECT_ITEM_BYTES)
            if not fits(used, cost(block)):
                break
            out.append(block)
            used += cost(block)
            i -= 1
        return out, i, skipped

    run, i, skipped = run_back(len(conversation) - 1, stop)
    older: list[str] = []
    if owner_block and owner_idx is not None and i == owner_idx:
        # The run reached the owner message, so the exchange is whole from there on: keep
        # going backward past it, still contiguous, while the share lasts (the room would
        # otherwise sit unused whenever the owner spoke last or second-to-last).
        older, _, _ = run_back(owner_idx - 1, -1)

    blocks: list[str] = list(reversed(older))
    if owner_block and owner_idx is not None:
        blocks.append(owner_block)
        # Skipped status replies after the owner's message are only in the full copy too
        # (TRDD-U119W52S); pure index arithmetic would not count them.
        gap = i - owner_idx + skipped
        if gap > 0:
            where = "between these" if run else "after this"
            blocks.append(f"[{gap} messages {where} are only in the full copy]")
    blocks.extend(reversed(run))
    return blocks, len(older) + len(run) + (1 if owner_block else 0)


def _inline_cost(it: Item, cap: int) -> int:
    """The exact bytes `render()` adds for `it` as a kept item under a per-item byte `cap`: the
    header line, the body (a verbatim prefix when over the cap) and, when over, the pointer
    line to the rest -- each `+1` for the "\\n" `render()` joins its lines with."""
    over = len(it.text.encode("utf-8")) > cap
    body = _truncate_prefix_bytes(it.text, cap) if over else it.text
    cost = len(f"-- {it.kind} {it.id} --\n{body}\n".encode("utf-8"))
    if over:
        cost += len(_format_pointer(it).encode("utf-8")) + 1
    return cost


_TAG_RE = re.compile(r"<[^>]{1,64}>")
_WHITESPACE_RE = re.compile(r"\s+")


def _body_chars(body: str) -> int:
    """TRDD-BLGZTHQ9 content gate: the non-whitespace characters left once short markup tags are
    stripped -- so a `<task-notification>` event cannot pass on its wrapper alone."""
    return len(_WHITESPACE_RE.sub("", _TAG_RE.sub("", body)))


_TOOL_CALL_ECHO_RE = re.compile(r"^[^\s(]+\(.*\)$")


def _tool_result_part(body: str) -> str:
    """TRDD-BLGZTHQ9 addendum (2026-09-24): `_segment_tool_result` always builds a "tool" item's
    text as `f"{name}({tool_input})\\n{result_text}"` -- its first line is that literal call
    echo, one line, ending in `)` right before the `\\n`. This strips exactly that line (never a
    naked tool body with no such echo, e.g. a unit-test fixture or a one-line real result whose
    first line just doesn't look like a call), so a call with an EMPTY result (`ToolSearch({...})`
    alone -- no `\\n` even -- or `name(...)\\n` with nothing after) reduces to `""` and fails the
    whole-tool-result gate instead of passing on its own name and arguments."""
    first, _, rest = body.partition("\n")
    return rest if _TOOL_CALL_ECHO_RE.match(first) else body


_NOTIFICATION_PREFIX = "<task-notification>"
# The WIDEST label `_notification_label` can return -- `_notification_block` sizes its reserve
# with it, so a shorter label only ever leaves the block a few bytes under its cap.
_NOTIFICATION_LABEL = "(excerpt: summary and result)"
_NOTIFICATION_ELEMENT_RE = re.compile(r"<(summary|result)>.*?</\1>", re.DOTALL)


def _notification_label(body: str) -> str:
    """The excerpt label naming only the elements whose text survived the cut in `body`.

    TRDD-BLGZTHQ9 F1b: the constant "(excerpt: summary and result)" claimed a result on
    notifications whose `<result>` the per-item cap had cut away entirely (fd5cc3e0 `a8ce36e6`,
    `e9b4733a`, 2026-09-24) or down to its heading (`f396cd9b`, `a0d1f47f`: `<result>ADVERSARIAL-
    REVIEW` and nothing else) -- a label is a claim about what is shown, so it is derived from it.
    A result "survives" only when its shown text, minus a bare one-token heading line, passes the
    same `_INJECT_MIN_BODY_CHARS` gate every inline item does: a heading is not a finding.
    """
    summary = body.partition("<summary>")[2].partition("</summary>")[0]
    result = body.partition("<result>")[2].partition("</result>")[0].strip()
    heading, sep, rest = result.partition("\n")
    if sep and len(heading.split()) == 1:
        result = rest
    parts = [name for name, ok in (("summary", _body_chars(summary) > 0),
                                   ("result", _body_chars(result) >= _INJECT_MIN_BODY_CHARS)) if ok]
    return f"(excerpt: {' and '.join(parts)})" if parts else "(excerpt)"


def _is_task_notification(it: Item) -> bool:
    """TRDD-BLGZTHQ9 (2026-09-24 addendum): only an `event` item wrapped in
    `<task-notification>...</task-notification>` gets the excerpt treatment below -- every
    other kind (including a plain `<cross-session-message>` event) keeps the existing
    whole/truncated-prefix path."""
    return it.kind == "event" and it.text.startswith(_NOTIFICATION_PREFIX)


def _task_notification_excerpt(text: str) -> str:
    """The `<summary>` and `<result>` elements of a `<task-notification>` event, each an EXACT
    substring of `text` (tags included, no paraphrase), in that order, joined by "\\n"; "" if
    neither is present. Measured on the real holdout transcript fd5cc3e0 (2026-09-24): the
    350-byte `<task-id>`/`<tool-use-id>`/`<output-file>`/`<status>` prefix alone cleared the
    80-char `_body_chars` gate on 3 of 3 inline non-owner items while saying nothing about what
    the sub-agent actually found -- only `<summary>`/`<result>` carry that, so the gate and the
    inline body both key on them instead of the wrapper."""
    return "\n".join(m.group(0) for m in _NOTIFICATION_ELEMENT_RE.finditer(text))


def _notification_block(it: Item, cap: int) -> tuple[str, int, str]:
    """The kept-item block for a `<task-notification>` event under per-item byte `cap`, its
    `_inline_cost`-style exact byte cost, and the excerpt body it SHOWS (before the label): the
    `_task_notification_excerpt` (a verbatim prefix of it when the excerpt alone would not fit
    alongside the label and pointer), the `_notification_label` marker, and -- coordinator
    addendum, unlike `_inline_cost`'s only-when-truncated pointer -- ALWAYS `_format_pointer`:
    an excerpt is never the whole wrapper, so the pointer is the only way back to the metadata
    the excerpt dropped, truncated or not. The shown body is returned so the selection's content
    gate measures what is rendered, not what exists (TRDD-BLGZTHQ9 F1b)."""
    excerpt = _task_notification_excerpt(it.text)
    pointer = _format_pointer(it)
    reserve = len(f"\n{_NOTIFICATION_LABEL}\n{pointer}".encode("utf-8"))
    body_cap = max(0, cap - reserve)
    body = (excerpt if len(excerpt.encode("utf-8")) <= body_cap
            else _truncate_prefix_bytes(excerpt, body_cap))
    block = f"{body}\n{_notification_label(body)}\n{pointer}"
    cost = len(f"-- {it.kind} {it.id} --\n{block}\n".encode("utf-8"))
    return block, cost, body


@dataclass(frozen=True)
class _InjectCandidate:
    """One item as `_select_injected` sees it: exact byte costs, no text (built by `compose`)."""

    id: str
    kind: ItemKind
    turn: int
    score: float  # the relevance answer
    inline_cost: int | None  # exact rendered bytes shown inline; None = never inline
    pointer_cost: int  # exact rendered bytes of its `[[elided id=...]]` line(s)
    pointer_eligible: bool  # False for a content-free non-owner item (counted, never pointed)
    # TRDD-SK490HKU: the exact rendered bytes of a Jev-kept, over-cap tool/event item shown
    # WHOLE (not a prefix) -- `_inline_cost(it, len(it.text.encode()))`, i.e. `cap == len(text)`
    # so no truncation branch fires. `None` for every item that is already inline via
    # `inline_cost` or a task-notification (excerpt-only, never whole). Default last so the
    # hand-built candidates in tests/test_jev_compaction.py keep compiling without naming it.
    whole_cost: int | None = None


@dataclass(frozen=True)
class _InjectSelection:
    kept: list[str]  # inline ids, in render order
    pointers: list[str]  # ordinary pointers (at most `max_pointers`)
    hidden: int  # everything else, for the count line
    # TRDD-SK490HKU: ids the second fill pass admitted WHOLE past their normal cap -- `compose`
    # reads this to build `relaxed_cap`, the per-id cap `render()` must use so an item costed
    # whole also RENDERS whole (advisor report 20260925_054459, item 1 point 3).
    whole: list[str] = field(default_factory=list)


def _select_injected(
    cands: list[_InjectCandidate], *, available: int | None, max_pointers: int,
) -> _InjectSelection:
    """The injected copy's whole selection (TRDD-BLGZTHQ9 + TRDD-U6C3YXEL): one priority-ordered
    fill of ONE running byte total over exact per-item costs, so the rendered document fits
    `available` by construction and the `max_bytes` backstop in `compose()` only ever acts on a
    pathological input (the fixed lines alone over budget).

    WHY one function instead of the tiers it replaced: the old injected branch kept four running
    totals plus a seven-stage backstop that re-decided everything admission decided, and five
    rounds in a row shipped the same regression -- a tier admitted against a budget nobody had
    reserved for the next tier (e.g. round 5's non-owner floor force-admitted over budget, then
    evicted again by the backstop). Here reservations are just fill order.

    `available` is the room left after the fixed lines (`None` = no byte limit). Every step
    admits only when `total + cost <= available`, with SKIP semantics: a miss never stops the
    walk, so a smaller item further down can still fit.
    """
    def fits(limit: int | None, used: int, cost: int) -> bool:
        return limit is None or used + cost <= limit

    def share(fraction: float) -> int | None:
        return None if available is None else int(available * fraction)

    def inline_cost(c: _InjectCandidate) -> int:
        if c.inline_cost is None:
            raise ValueError(f"{c.id} is not an inline candidate")
        return c.inline_cost

    total = 0  # exact bytes of: inline items + ordinary pointers
    inline_ids: set[str] = set()

    def admit(c: _InjectCandidate) -> bool:
        """Inline `c` if the document still fits."""
        nonlocal total
        new_total = total + inline_cost(c)
        if available is not None and new_total > available:
            return False
        total = new_total
        inline_ids.add(c.id)
        return True

    # 1. The non-owner floor (owner ruling aabd8b0c: "the resumed session learns what was
    #    DONE"), reserved first and never over budget -- met by reservation,
    #    not by overrun plus eviction (the round-5 defect). No `protected` term: a 350-B slice
    #    of a diff must not outrank prose. TRDD-R9UXOSR5: the guaranteed-owner slot (old step
    #    1, owner ruling fe38e095) went with the decision question -- no owner item is ever a
    #    scored candidate any more, so there is no owner tier to guarantee.
    non_owner_order = sorted(
        (c for c in cands if c.inline_cost is not None),
        key=lambda c: (c.score, c.turn), reverse=True,
    )
    non_owner: list[_InjectCandidate] = []
    for c in non_owner_order:
        if len(non_owner) >= _NON_OWNER_FLOOR:
            break
        if fits(available, total, inline_cost(c)):
            non_owner.append(c)
            inline_ids.add(c.id)
            total += inline_cost(c)

    # 2. Non-owner items beyond the floor, same order as step 1.
    non_owner += [c for c in non_owner_order if c.id not in inline_ids and admit(c)]

    # 2b. TRDD-SK490HKU: second fill pass -- spend whatever room remains on a Jev-kept, over-cap
    # tool/event item WHOLE, highest score first, each only if its exact whole rendered cost
    # fits what is left (never a prefix -- TRDD-BLGZTHQ9 holds). Runs BEFORE step 3's ordinary
    # pointers (not after) so an admitted item's pointer bytes are never spent at all, rather
    # than spent and then refunded -- advisor report 20260925_054459, item 1 point 2: this is
    # also what lets a room reclaim an already-assigned pointer's bytes for a bigger whole item.
    # `whole_cost` is only ever set (see `_InjectCandidate`) for a candidate not already inline,
    # so this never re-admits one of steps 1-2's own picks.
    whole: list[str] = []
    for c in sorted(
        (c for c in cands if c.whole_cost is not None and c.id not in inline_ids),
        key=lambda c: (c.score, c.turn), reverse=True,
    ):
        cost = c.whole_cost
        assert cost is not None  # narrowed by the generator's own filter above; mypy can't see it
        if fits(available, total, cost):
            whole.append(c.id)
            inline_ids.add(c.id)
            total += cost

    # 6. Ordinary pointers (amendment S1: every item not inline -- elided by the token stage or
    #    excluded here), highest score first, capped by count (`max_pointers`) and by
    #    `_INJECT_POINTER_SHARE`. TRDD-R9UXOSR5: the decision-pointer reserve (old step 3,
    #    TRDD-U6C3YXEL) went with the decision question.
    pointer_cap = share(_INJECT_POINTER_SHARE)
    pointers: list[str] = []
    pointer_bytes = 0
    for c in sorted(
        (c for c in cands if c.id not in inline_ids and c.pointer_eligible),
        key=lambda c: c.score, reverse=True,
    ):
        if len(pointers) >= max_pointers:
            break
        if fits(pointer_cap, pointer_bytes, c.pointer_cost) and fits(available, total,
                                                                     c.pointer_cost):
            pointers.append(c.id)
            pointer_bytes += c.pointer_cost
            total += c.pointer_cost

    # TRDD-SK490HKU: `whole` sits right after `non_owner` in render order -- the backstop's
    # stage (2) evicts non-owner items in reverse `kept_order`, so a whole-admitted item (the
    # largest, lowest-priority of the non-owner set) is the FIRST thing sacrificed if the
    # pathological backstop ever has to run at all.
    kept = [c.id for c in non_owner] + whole
    # TRDD-U6C3YXEL: the count line names EVERYTHING not shown -- it used to omit every byte-
    # stage exclusion, so "681 more" hid 21 owner messages.
    hidden = len(cands) - len(kept) - len(pointers)
    return _InjectSelection(kept=kept, pointers=pointers,
                            hidden=hidden, whole=whole)


def compose(
    items: list[Item],
    scores: dict[str, Scores],
    *,
    budget_tokens: int = 8000,
    header: dict[str, Any],
    max_elided_pointers: int = _MAX_ELIDED_POINTERS,
    max_bytes: int | None = None,
    full_context_path: str | None = None,
    max_item_bytes: int | None = None,
    non_owner_item_bytes: int | None = None,
    conversation: list[Item] | None = None,
    conversation_summary: str | None = None,
) -> str:
    """Assemble the final injected document: header, kept items verbatim, then pointers.

    `conversation` / `conversation_summary` (TRDD-D7RLXAN1, owner directive 2026-09-24: "assistant
    prose and user prose (the messages exchanges) should be all kept intact"): the live owner/
    assistant/control messages `split_conversation` kept OUT of scoring, and Claude Code's own
    compaction summary. The FULL render (`max_item_bytes is None`) prints both, every message
    whole and in order, before the kept items. The injected render prints the newest exchanges
    (`_select_exchanges`) within `_INJECT_EXCHANGE_SHARE` of the room left by its fixed lines;
    the block is part of `render()`'s fixed text, so `_select_injected` fits the tool/event
    items into what remains and the `max_bytes` guarantee below is untouched.

    `header` carries: `transcript_path`, `session_key`, `digest`, and an optional `usage`
    dict (`{"tokens": int, "cost": float}` from the Jev response). The transcript path is
    written out exactly ONCE by design (TRDD-EFA4P42B: it used to appear up to four times --
    the header, the "N more items" line, the "Full compacted context" line, and the trailer --
    costing ~580 B of a ~1,360 B fixed baseline inside a ~3 KB injected room) -- only in the
    fixed trailing "expand with" line -- never inside an individual pointer.

    `full_context_path`, when given (card 5 two-renderings, TRDD-RAEGS1D5): this render is a
    CAPPED companion to a separate, uncapped `compose()` call over the SAME `items`/`scores`
    ("score once, render twice" -- the caller never re-scores). TRDD-D7RLXAN1: the document's
    FIRST line is then `_read_first_line` naming that path -- the full copy holds every message
    since the last compaction, which the owner ruled must be read in full (Q1, 2026-09-24). It
    replaced the old trailing "Full compacted context: <path> -- read it ONLY if ..." line, which
    would contradict it (advisor finding C: the parameter stays, its consumer changed).

    `max_bytes`, when given, is a BACKSTOP (card 5 content-fit, TRDD-RAEGS1D5): the caller is
    expected to size `budget_tokens` / the digest / `max_elided_pointers` so the document
    already fits in the common case (measured: reports/compaction-replacement/ -- the pointer
    list, not the kept-items budget, dominated the old default). This only degrades further
    when a PARTICULAR transcript still overflows -- e.g. an unusually verbose digest or long
    pointer previews -- and it degrades in priority order, never a blind byte slice (TRDD-
    RAEGS1D5, compose() budget floor round 5 -- coordinator ruling on the round 4 regression: a
    pointer is a breadcrumb to an item still fully recoverable via `expand --list --grep` --
    losing one costs far less than a KEPT item vanishing with NO trace at all (the pointers,
    `shown_elided`, are chosen once, before this backstop runs, so an item evicted here is
    never added back as a pointer). But the round 4 attempt at "cheapest sacrifice first"
    literally sacrificed EVERY non-owner item before a single non-guaranteed-owner one, which
    measurably emptied the non-owner tier on real data -- reintroducing, inside the backstop
    specifically, the exact failure commit aabd8b0c ("jev newest+3") fixed at admission time.
    Owner ruling: "the at-least-3 non-owner target stands; its purpose is that the resumed
    session learns what was DONE". So:
      (1) drop pointers LOWEST-SCORE-first (the ones already least likely to be worth
          expanding) -- can empty the elided-pointer list entirely;
      (2) evict NON-OWNER kept items (`kind != "user"`), lowest priority first, but only DOWN TO
          a floor of `_NON_OWNER_FLOOR` (3) -- stops short of the floor even if the doc still
          does not fit, deferring to (3) first;
      (3) evict NON-GUARANTEED-OWNER kept items (`kind == "user"`, excluding the guaranteed
          slot below), lowest priority first;
      (4) only once (2)+(3) together are still not enough, come back for the last
          `_NON_OWNER_FLOOR` non-owner items -- the SAME lowest-priority-first order (2) already
          computed and stopped partway through, now continued with no floor;
      (5) truncate the digest text itself.
    When `max_item_bytes` is unset (TRDD-RAEGS1D5: the `budget_tokens` eviction above now admits
    by an owner-share-capped order instead, but this narrower byte-only fallback keeps
    `evict_key`'s plain (protected, max_score) rule for (2)-(4), unchanged) -- lowest
    first, oldest among ties -- never bare chronological order, so an older kept item is not
    sacrificed ahead of a newer, lower-priority one just for being older. The trailing
    "pointers expand with:" line is NEVER dropped by stages (1)-(5) --
    it is the model's only way back to everything elided, and a blind `raw[:room]` slice
    downstream (`external_clear.compose_handoff`, before an earlier fix) used to cut it off
    along with the newest kept items because both sit at the tail of the joined string.

    (6) the SOLE exception (TRDD-RAEGS1D5, budget floor round 3): `render()`'s own fixed lines
    -- header, section headings, that same trailing line -- embed `transcript_path` (TRDD-
    EFA4P42B: once, in the trailer, since the header/elided-line/full-context-line copies were
    removed) and `full_context_path` once, so stages (1)-(5) alone cannot guarantee the fixed
    skeleton itself fits a small `max_bytes` or survives a long transcript path. Only once
    (1)-(5) still leave the render over budget, the ENTIRE document -- trailer included -- is
    replaced by `_render_minimal_fallback`'s constant-size marker plus the newest OWNER message
    (from the conversation, else the guaranteed slot) truncated to whatever room remains,
    or `""` when nothing fits at all -- the one item no stage above ever sacrifices, per the
    owner ruling "the owner's newest message first" (fe38e095) -- it is dropped LAST, if at
    all. This is the function's actual, load-bearing guarantee: `max_bytes`, when given, is
    NEVER exceeded by the return value, not merely "usually" or "in the common case" above.

    Within the `budget_tokens` admission itself (TRDD-R9UXOSR5): one flat priority fill --
    protected segments first, then relevance -- over every kept item. An item that does not
    fit becomes an ordinary elided pointer. TRDD-R9UXOSR5: the old decision-pointer uncap and hard ceiling (every
    elided `decision_passed` item uncapped, then capped at 400 -- TRDD-RAEGS1D5) went with the
    decision question; `_MAX_ELIDED_POINTERS` again caps every elided item alike, selected by
    `_pointer_priority` (protected first, then score). The injected copy selects its own
    pointers -- see `max_item_bytes` below.

    `max_item_bytes`, when given (the injected copy; `--out` never passes it): after the shared
    `budget_tokens` stage, what is shown inline, what gets a pointer and what is only counted is
    decided by `_select_injected` (TRDD-BLGZTHQ9), which fits the render to
    `max_bytes` by construction; see its docstring for the fill order and why. Kept items then
    render in that selection's priority order, not chronologically, and a kept item over its
    per-item cap renders as a verbatim prefix plus a pointer to the rest. `evict_key` only
    governs the narrower byte-only backstop below (when `max_item_bytes` is unset but
    `max_bytes` still is) -- the token-budget admission above, shared by BOTH renderings, no
    longer uses it alone (TRDD-RAEGS1D5: see the owner-share comment there for why a plain
    `evict_key` sort starved `--out` of every non-owner item).

    `non_owner_item_bytes`, when given alongside `max_item_bytes` (TRDD-RAEGS1D5, jev
    newest+3): the per-item byte cap `render()` applies to a KEPT item whose `kind != "user"`
    -- every owner item (guaranteed or not) still uses `NEWEST_OWNER_ITEM_BYTES`/
    `max_item_bytes` exactly as before. See `DEFAULT_INJECT_NON_OWNER_ITEM_BYTES`'s own
    comment for the real-transcript defect this closes (owner items and non-owner items
    sharing one cap left too few of the latter in a tight injected render). `None` (the
    default) keeps every existing caller's behaviour -- non-owner items fall back to
    `max_item_bytes`, same as before this parameter existed.
    """
    # TRDD-DQXMND59 stage 3b item B: sanitize every str input `compose()` receives at this ONE
    # boundary, instead of trusting each source separately (a lone surrogate reaching a bare
    # f-string/print below raises UnicodeEncodeError). `header`'s string values, `full_context_
    # path`, and `conversation_summary` are the parameters this function itself ever embeds
    # verbatim into `render()`'s output; `conversation`/`items` are `Item`s, already sanitized on
    # construction by `Item.__post_init__` (items are DATA, not parameters -- untouched here).
    header = {
        k: (jsonl_walk.drop_lone_surrogates(v) if isinstance(v, str) else v)
        for k, v in header.items()
    }
    if full_context_path is not None:
        full_context_path = jsonl_walk.drop_lone_surrogates(full_context_path)
    if conversation_summary is not None:
        conversation_summary = jsonl_walk.drop_lone_surrogates(conversation_summary)

    # Oversized is re-checked here, not just trusted from `scores[...].kept`, because
    # "never inlined" is the compose-time invariant the spec actually cares about -- this
    # function is where inlining happens, so this is where the guard has to hold even if a
    # caller builds `scores` by hand (as the tests do) instead of via `score_items`.
    # TRDD-R9UXOSR5: the old unconditional force-admit of the newest owner item (owner ruling
    # fe38e095, "the owner's newest message first") went with the decision question -- no
    # owner item is ever a scored candidate any more, so there is no owner slot to guarantee;
    # owner prose reaches the document through `conversation` instead (TRDD-D7RLXAN1).
    kept_items = [
        it for it in items if scores[it.id].kept and not scores[it.id].oversized
    ]

    def max_score(it: Item) -> float:
        return scores[it.id].relevance

    # Card 6 follow-up (coordinator review of commit 3006e92f, addition 2): on a real 258 MB
    # transcript, 3 segments of ONE diff (`Item.protected`) outcompeted segments/whole items
    # from 3 OTHER tool results for the same fixed budget -- card 6's own acceptance
    # criterion is MORE DISTINCT tool results kept, not more segments of the one that happens
    # to be a diff/stacktrace. At most one segment per SOURCE item (`_source_item_id`) keeps
    # the `protected`-tier priority boost below: the highest-`max_score` segment of that
    # source item (ties broken by the earliest `turn` -- segments of one block consume
    # consecutive turns, so this is simply the first one). Any FURTHER segment of the same
    # source item competes purely by relevance/recency, the same tier a plain item gets.
    # The winner is chosen from `kept_items` ONLY, never from `items` (adversarial review of
    # this change): `score_items` gives an oversized item relevance=1.0 and
    # `kept=False`, so over `items` an oversized segment always wins the boost for its source
    # yet never reaches any ranking below -- leaving ZERO of that source's kept segments
    # boosted instead of one.
    _protected_boost_key: dict[str, tuple[float, int]] = {}
    _protected_boost_id: dict[str, str] = {}
    for it in kept_items:
        if not it.protected:
            continue
        src = _source_item_id(it.id)
        key = (max_score(it), -it.turn)
        if src not in _protected_boost_key or key > _protected_boost_key[src]:
            _protected_boost_key[src] = key
            _protected_boost_id[src] = it.id

    def _effective_protected(it: Item) -> bool:
        return it.protected and _protected_boost_id.get(_source_item_id(it.id)) == it.id

    def evict_key(it: Item) -> tuple[bool, float, int]:
        # (protected, max_score, turn) ascending: a relevance-only item sorts, and is
        # dropped, BEFORE any `protected` segment. Card 6 (TRDD-88DOI824): a `protected`
        # segment (stacktrace/diff, see `Item.protected`) is structurally important even when
        # Jev scores it as merely-relevant. Within each tier, lowest score first, oldest
        # (smallest `turn`) among equal scores. `_effective_protected` (not the raw
        # `it.protected`), per the "at most one segment per source item" cap above.
        # TRDD-R9UXOSR5: the old leading `decision_passed` term went with the decision
        # question -- every scored item is now relevance-only.
        return (_effective_protected(it), max_score(it), it.turn)

    total_tokens = sum(it.tokens for it in kept_items)
    kept_ids = {it.id for it in kept_items}
    if total_tokens > budget_tokens:
        # TRDD-RAEGS1D5 (release blocker): admit by a priority order instead of the old plain
        # `evict_key` removal loop. Measured on this repo's own 49 MB transcript (d30bf250,
        # reports/compaction-replacement/): under the pre-card-5 evict_key sort, 28 "user"
        # items alone totaled 14298 tokens, already over the 8000-token default
        # `budget_tokens`, so every one of the 158 relevance-passing tool/assistant/event
        # items (of 4141/1725/171 scored) was evicted first and NONE survived -- a resumed
        # session then only ever saw what the owner asked, never what was done.
        # TRDD-R9UXOSR5: the old owner-share stage on top of this went with the decision
        # question -- `score_items` no longer produces a "user" group, so the token
        # admission is one flat priority fill over every kept item.
        admitted: list[Item] = []
        admitted_tokens = 0
        for it in sorted(
            (it for it in kept_items),
            # Card 6 (TRDD-88DOI824): `_effective_protected(it)` (stacktrace/diff, capped to
            # one segment per source item -- see that helper's own comment) ranks above plain
            # relevance -- same tier as `evict_key`/`_pointer_priority` above, so a
            # structurally-important segment is not starved out of the budget by a
            # merely-more-relevant sibling. TRDD-R9UXOSR5: the old owner-share stage went
            # with the decision question -- one flat priority fill.
            key=lambda it: (
                _effective_protected(it), max_score(it), it.turn,
            ),
            reverse=True,
        ):
            if admitted_tokens + it.tokens > budget_tokens:
                continue  # a smaller lower-priority item further down may still fit
            admitted.append(it)
            admitted_tokens += it.tokens
        kept_ids = {it.id for it in admitted}
        total_tokens = admitted_tokens

    def _pointer_priority(it: Item) -> tuple[bool, float]:
        # Card 6 (TRDD-88DOI824): a `protected` segment (stacktrace/diff) gets first claim on
        # the pointer slots over any merely-more-relevant item; capped to one segment per
        # source item, per `_effective_protected`'s own comment. TRDD-R9UXOSR5: the old
        # leading `decision_passed` term went with the decision question.
        return (_effective_protected(it), max_score(it))

    # TRDD-SK490HKU: per-id cap override for an item the second fill pass (`_select_injected`
    # step 2b) admitted WHOLE past its normal `non_owner_item_bytes` cap -- a name `render()`
    # reads at call time, so every render
    # (the backstop's re-renders included) agrees with what the selection actually costed. Set
    # below once `selection.whole` is known; empty here so the pre-selection baseline render
    # (which has no kept items yet) is unaffected.
    relaxed_cap: dict[str, int] = {}

    transcript_path = header.get("transcript_path", "")
    usage = header.get("usage") or {}

    # TRDD-D7RLXAN1: the conversation section and the READ FIRST line -- FIXED text for render(),
    # which reads both names at call time. Filled in below, after the injected render's baseline
    # without them is measured (the exchange budget is a share of the room that baseline leaves).
    conversation_lines: list[str] = []
    read_first = ""

    def render(
        kept_order: list[Item], elided: list[Item], hidden: int, digest_text: str,
    ) -> str:
        lines: list[str] = [
            *([read_first] if read_first else []),
            "# Compacted context (Jev compaction)",
            f"session: {header.get('session_key', '')}",
            "",
        ]
        # TRDD-EFA4P42B: the header used to also print `transcript: {transcript_path}` -- the
        # trailer below already carries the same path for the model's `expand` command, and
        # that was the SECOND of four total copies (~580 B of a ~1,360 B fixed baseline inside
        # a ~3 KB injected room) with no reader who needed it repeated. Dropped here; the
        # trailer is now the ONLY place `transcript_path` appears.
        #
        # An empty digest (`--inject-out` always forces one, see jev_compact.py) still costs a
        # "## Digest" heading plus an empty line plus a "usage: ..." line for nothing in the
        # byte-capped injected render (`max_item_bytes is not None`) -- the `--out` render has
        # no such cap and keeps a stable, always-shaped document regardless.
        if digest_text or max_item_bytes is None:
            lines.append("## Digest")
            lines.append(digest_text)
            lines.append("")
            lines.append(f"usage: tokens={usage.get('tokens', '?')} cost={usage.get('cost', '?')}")
            lines.append("")
        lines.extend(conversation_lines)
        lines.append("## Kept items")
        for it in kept_order:
            lines.append(f"-- {it.kind} {it.id} --")
            # A non-owner item, when `non_owner_item_bytes` is given, gets ITS OWN (smaller)
            # cap instead of `max_item_bytes` -- see that parameter's own docstring. An owner
            # item (a conversation-kind item a test built directly) keeps `max_item_bytes`.
            # TRDD-R9UXOSR5: the old guaranteed-owner cap exception
            # (`guaranteed_item_cap`, `NEWEST_OWNER_ITEM_BYTES` via
            # `_INJECT_NEWEST_OWNER_SHARE`) went with the decision question.
            cap = (
                non_owner_item_bytes
                if (
                    max_item_bytes is not None
                    and non_owner_item_bytes is not None
                    and it.kind != "user"
                )
                else max_item_bytes
            )
            # TRDD-SK490HKU: an item the second fill pass admitted WHOLE past its normal cap
            # must also RENDER whole, or the document shrinks while the item silently reverts
            # to a pointer -- `relaxed_cap` is exactly `len(it.text.encode())` for such an id
            # (see `_InjectSelection.whole`), so the `len(text_bytes) > cap` check below never
            # fires for it. `--out` (max_item_bytes is None) never populates `relaxed_cap`.
            cap = relaxed_cap.get(it.id, cap)
            if max_item_bytes is not None and cap is not None and _is_task_notification(it):
                # TRDD-BLGZTHQ9 addendum: injected-only (max_item_bytes is not None) -- the
                # `--out` render (max_item_bytes is None) must stay byte-identical, so it never
                # takes this branch and keeps showing `it.text` whole below.
                block, _, _ = _notification_block(it, cap)
                lines.append(block)
                continue
            text_bytes = it.text.encode("utf-8")
            if cap is not None and len(text_bytes) > cap:
                # TRDD-SK490HKU: 90e890ce's "over-cap non-owner item is pointer-only" branch is
                # deleted here -- `_select_injected` only ever inlines a tool/event item when it
                # is `whole` under its normal cap OR admitted whole under `relaxed_cap` (the
                # second fill pass), so no over-cap tool/event item ever reaches `kept_order`
                # with `cap` unchanged; that guard was reachable only if the selection and this
                # render ever disagreed, and a defense-in-depth branch that silently prints a
                # pointer for an item costed whole HIDES that disagreement instead of surfacing
                # it (CLAUDE.md: no fallback that hides a bug). One path now, for every kind:
                # TRDD-RAEGS1D5 requirement 2's verbatim prefix, never a paraphrase, plus a
                # pointer back to the rest -- see `_truncate_prefix_bytes`'s own docstring for
                # why this is what stops one oversized-relative-to-budget owner item from being
                # evicted whole the way the old byte backstop did.
                lines.append(_truncate_prefix_bytes(it.text, cap))
                lines.append(_format_pointer(it))
            else:
                lines.append(it.text)

        lines.append("")
        lines.append("## Elided")
        elided_ids = {it.id for it in elided}
        for it in items:
            if it.id in elided_ids:
                lines.append(_format_pointer(it))
                if scores[it.id].oversized:
                    # TRDD-RAEGS1D5 requirement 4: the 20-line oversized preview is fine in
                    # the full `--out` document (max_item_bytes is None there) but must NEVER
                    # reach the byte-capped injected copy -- it is exactly the kind of large,
                    # low-value block the cap exists to keep out of a resumed session.
                    if max_item_bytes is None:
                        lines.append(_oversized_preview(it))
                elif scores[it.id].blocked:
                    # TRDD-1ETALGDG followup: this item was never sent to Jev at all (a
                    # provider firewall block or an oversized batch survived every split
                    # retry, see score_items) -- distinct from an ordinary below-threshold
                    # item, which WAS judged and found not relevant. Without this the model
                    # cannot tell "Jev never got to see this" apart from "Jev saw it and it
                    # wasn't worth keeping", and only the former is worth a manual `expand`.
                    lines.append("unscored (provider firewall)")
        if hidden:
            # Card 5 content-fit (TRDD-RAEGS1D5, item 3): a bare "N more items not listed" was
            # a dead end -- `expand` needs an id, and an id not shown here could never be
            # named. `--list [--grep TEXT]` (mentioned alongside this line) walks the SAME
            # transcript and prints every item's id, so this points the model at that instead
            # of leaving it to guess or give up.
            #
            # TRDD-EFA4P42B: this used to spell out the whole `expand --transcript <path>
            # --list --grep TEXT` command (the THIRD of four `transcript_path` copies) --
            # pointing at "the expand command below" (the trailer, which already carries the
            # same path) says the same thing without repeating the path.
            # TRDD-EFA4P42B followup: "append ... to the expand command below" was wrong --
            # the trailer ends in a literal `<id>`, and appending after it makes `<id>` a
            # shell redirect target. `<id>` is a placeholder to REPLACE, not a tail to extend,
            # so this now says "replace <id> ... with". The literal `--list --grep` text
            # stays -- a test greps for it.
            lines.append(
                f"[[elided: {hidden} more items not listed -- list/search: replace <id> in "
                "the expand command below with --list --grep TEXT]]"
            )

        lines.append("")
        lines.append(
            'pointers expand with: uv run --script "$CLAUDE_PLUGIN_ROOT/scripts/jev_compact.py" '
            f"expand --transcript {transcript_path} <id>"
        )
        return "\n".join(lines)

    digest_text = header.get("digest", "")

    # TRDD-D7RLXAN1: the conversation, never scored -- see the docstring. Full render: the
    # summary and every live message, whole. Injected render: the newest exchanges within their
    # share of the room the fixed lines leave (READ FIRST and heading charged inside the share).
    n_messages = len(conversation or [])
    shown_messages = n_messages
    if max_item_bytes is None:
        if conversation is not None or conversation_summary is not None:
            conversation_lines = [_CONVERSATION_HEADING]
            if conversation_summary is not None:
                conversation_lines += [_SUMMARY_HEADING, conversation_summary, ""]
            conversation_lines += [_exchange_block(it, None) for it in conversation or []]
            conversation_lines.append("")
    else:
        exchange_budget = (
            None if max_bytes is None
            else int(max(0, max_bytes - len(render([], [], len(items), digest_text).encode("utf-8")))
                     * _INJECT_EXCHANGE_SHARE)
        )
        if exchange_budget is not None:
            if full_context_path:  # at its widest: `shown` only ever shrinks the line
                exchange_budget -= len(_read_first_line(
                    full_context_path, n_messages, n_messages).encode("utf-8")) + 1
            exchange_budget -= len(_EXCHANGES_HEADING.encode("utf-8")) + 2  # + trailing blank
        blocks, shown_messages = _select_exchanges(conversation or [], exchange_budget)
        if blocks:
            conversation_lines = [_EXCHANGES_HEADING, *blocks, ""]
    if full_context_path:
        read_first = _read_first_line(full_context_path, n_messages, shown_messages)

    if max_item_bytes is not None:
        # TRDD-BLGZTHQ9 + TRDD-U6C3YXEL: the injected copy's selection, as one pure fill over
        # exact per-item costs (see `_select_injected`). The fixed lines are measured with the
        # count line at its WIDEST (`hidden=len(items)`): it only shrinks as items are shown,
        # and disappears at 0, so counting every excluded item can never break the fit -- the
        # monotone form of the count fix the TRDD-AW4XD53Q review had to revert.
        baseline = len(render([], [], len(items), digest_text).encode("utf-8"))
        available = None if max_bytes is None else max(0, max_bytes - baseline)
        non_owner_cap = non_owner_item_bytes if non_owner_item_bytes is not None else max_item_bytes
        cands: list[_InjectCandidate] = []
        for it in items:
            s = scores[it.id]
            # Mirrors render()'s "## Elided" branch: pointer line, plus the firewall note for a
            # blocked item (the oversized preview is --out only).
            pointer_cost = len(_format_pointer(it).encode("utf-8")) + 1
            if s.blocked and not s.oversized:
                pointer_cost += len("unscored (provider firewall)") + 1
            # TRDD-U6C3YXEL amendment S1, re-read 2026-09-24: a NON-owner item may be inline when
            # Jev kept it (the same test `kept_items` applies), not only when the `budget_tokens`
            # stage admitted it. That stage ranks by score, so on real sessions it filled its
            # 8,000 tokens with a few large tool results -- which this copy can only point at
            # (a tool over its cap is never a prefix) -- and the small kept results it skipped
            # could not be shown either: 0 tool/event items inline on d30bf250, 2 on 4eb7bf5d
            # (reports/compaction-replacement/20260924_180444+0200-d7rlxan1-implementation.md,
            # Finding 2). The copy is still a subset of what Jev kept, and its own byte fill
            # (`_select_injected`) still decides which of them fit. Owner items keep the token
            # stage's set: its owner share and caps are theirs, and D7RLXAN1 moved live owner
            # prose out of `items` anyway.
            jev_kept = s.kept and not s.oversized
            # TRDD-SK490HKU: only the plain tool/event branch below ever sets this to a real
            # cost -- a "user" item has its own share-capped tiers, and a task-notification's
            # excerpt is never shown whole (see `_InjectCandidate.whole_cost`'s own docstring).
            whole_cost: int | None = None
            if it.kind == "user":
                cap = max_item_bytes
                # Amendment S1: only what the token stage kept may be inline -- the injected
                # copy stays a subset of what Jev kept; everything else can only be pointed at.
                inline_cost = _inline_cost(it, cap) if it.id in kept_ids else None
                pointer_eligible = True
            elif _is_task_notification(it):
                # Coordinator addendum (2026-09-24): a task-notification's gate and inline body
                # are the `<summary>`/`<result>` excerpt alone, never the id/path/status wrapper
                # -- see `_task_notification_excerpt`. Never "whole": `_notification_block`
                # always appends the pointer, so it is never exempt from `pointer_eligible`.
                excerpt = _task_notification_excerpt(it.text)
                # The POINTER gate stays on the full excerpt: the pointer leads back to all of it.
                pointer_eligible = _body_chars(excerpt) >= _INJECT_MIN_BODY_CHARS
                _, block_cost, shown = _notification_block(it, non_owner_cap)
                # TRDD-BLGZTHQ9 F1b: the INLINE gate must measure what is shown, not what exists.
                # The shown body is the excerpt cut to the cap minus label and pointer, and the
                # cut backs off to the last newline -- measured on fd5cc3e0 (2026-09-24), 4 of 6
                # inline notifications passed on their full excerpt (557-3371 chars) but rendered
                # only the agent's title (45-56 chars), ~990 B of a 4,000-B room for four titles.
                # Such an item is pointer-only, and its bytes go to the next candidate.
                inline_ok = (jev_kept and pointer_eligible
                             and _body_chars(shown) >= _INJECT_MIN_BODY_CHARS)
                inline_cost = block_cost if inline_ok else None
            else:
                whole = len(it.text.encode("utf-8")) <= non_owner_cap
                body = it.text if whole else _truncate_prefix_bytes(it.text, non_owner_cap)
                # TRDD-BLGZTHQ9 addendum: the 20-char whole-tool-result gate counts only the
                # RESULT part -- see `_tool_result_part`'s own docstring for why a bare call
                # echo with no result (e.g. `ToolSearch({...})` alone) fails the gate instead of
                # passing on its own name and arguments.
                gate_body = _tool_result_part(body) if whole and it.kind == "tool" else body
                # Amendment S3: 20 chars for a whole tool result ("...  [100%]\n3 passed in
                # 0.18s" survives), 80 for prose/events (a non-owner item is never a
                # truncated prefix now -- see `inline_ok` below).
                min_chars = (_INJECT_MIN_WHOLE_TOOL_BODY_CHARS if whole and it.kind == "tool"
                             else _INJECT_MIN_BODY_CHARS)
                pointer_eligible = _body_chars(gate_body) >= min_chars
                # TRDD-BLGZTHQ9 (extended past kind == "tool" to kind == "event" too, e.g. a
                # cross-session-message that is not a task-notification -- "tool" and "event"
                # are exactly the two kinds `split_conversation` ever scores, see
                # `_CONVERSATION_KINDS`; an "assistant"/"control" item never reaches this
                # branch in production and keeps the old prefix-eligible path for the tests
                # that exercise it directly): a scored item over the cap is a pointer, never
                # a prefix -- the pointer's preview already says WHAT it is, and a 350-B
                # slice of a diff/grep/Bash result (or of a peer message cut mid-sentence)
                # added a few lines for 3-4x the bytes. `whole` gates both kinds now, keyed on
                # the SAME `_CONVERSATION_KINDS` constant render()'s guard uses (not a second,
                # independently-written kind list) -- adversarial review of this fix flagged a
                # literal `("tool", "event")` tuple here as silently divergent from render()'s
                # `_CONVERSATION_KINDS` guard the moment `ItemKind` ever grows a 6th member; one
                # shared constant means a new kind is non-owner (pointer-only-when-over-cap) or
                # conversation (verbatim-prefix) in both places at once, never just one.
                inline_ok = (jev_kept and pointer_eligible
                             and (whole or it.kind in _CONVERSATION_KINDS))
                inline_cost = _inline_cost(it, non_owner_cap) if inline_ok else None
                # TRDD-SK490HKU: the second fill pass's own candidate cost -- this item's exact
                # WHOLE rendered cost (`cap == len(text)`, so `_inline_cost` never truncates),
                # set only for a Jev-kept, pointer-eligible, over-cap item that did NOT already
                # get an `inline_cost` above (`inline_cost is None`) -- a "tool"/"event" item
                # over its cap (`inline_ok` False there), never a conversation-kind one, which
                # `inline_ok` already admits at `non_owner_cap` regardless of `whole`, and never
                # a task-notification (its own excerpt-only path, above). `_select_injected`
                # step 6b spends leftover room on these, highest score first, never producing a
                # prefix (TRDD-BLGZTHQ9 holds).
                whole_cost = (_inline_cost(it, len(it.text.encode("utf-8")))
                              if jev_kept and pointer_eligible and not whole
                              and inline_cost is None else None)
            cands.append(_InjectCandidate(
                id=it.id, kind=it.kind, turn=it.turn, score=max_score(it),
                inline_cost=inline_cost, pointer_cost=pointer_cost,
                pointer_eligible=pointer_eligible, whole_cost=whole_cost,
            ))
        selection = _select_injected(cands, available=available,
                                     max_pointers=max_elided_pointers)
        by_id = {it.id: it for it in items}
        # TRDD-SK490HKU: fill `relaxed_cap` before the first render() that can hit a `whole`
        # id (2776) -- every later re-render (the backstop's included) then agrees with what
        # the selection actually costed, the exact-fit invariant `_select_injected`'s own
        # docstring promises.
        relaxed_cap.update({i: len(by_id[i].text.encode("utf-8")) for i in selection.whole})
        kept_order_list = [by_id[i] for i in selection.kept]
        # render() walks `items` for the "## Elided" list, so pointers stay chronological.
        shown_elided = [by_id[i] for i in selection.pointers]
        hidden_count = selection.hidden
    else:
        # `items` is already chronological, so filtering it (rather than re-sorting) keeps the
        # elided list chronological for free -- `max_elided_pointers` below only needs to pick
        # WHICH ids survive, not reorder anything.
        elided_items = [it for it in items if it.id not in kept_ids]
        hidden_count = 0

        # TRDD-R9UXOSR5: one pointer class again. The old decision-pointer uncap + hard
        # ceiling (TRDD-RAEGS1D5) split elided items into `decision_elided`/`other_elided`
        # and gave the former up to `_MAX_DECISION_POINTERS` compact `id: preview` lines;
        # both went with the decision question, so `max_elided_pointers` caps every elided
        # item alike, ranked by `_pointer_priority`.
        if len(elided_items) > max_elided_pointers:
            # Highest priority first -- protected segments before plain items, highest
            # relevance as the tiebreak -- the items most worth a pointer are the ones the
            # model was closest to keeping, not an arbitrary chronological head/tail.
            top_ids = {
                it.id
                for it in sorted(elided_items, key=_pointer_priority, reverse=True)[:max_elided_pointers]
            }
            shown_elided = [it for it in elided_items if it.id in top_ids]
            hidden_count = len(elided_items) - len(shown_elided)
        else:
            shown_elided = elided_items
        kept_order_list = [it for it in items if it.id in kept_ids]  # `items` is chronological

    doc = render(kept_order_list, shown_elided, hidden_count, digest_text)
    if max_bytes is None or len(doc.encode("utf-8")) <= max_bytes:
        return doc

    # Backstop degrade, in priority order -- see the docstring for the full rationale (round 5
    # coordinator ruling, on the round 4 regression report). Each step only runs if the
    # previous ones were not enough; lists are popped from one end so this is bounded (at most
    # `len(items)` iterations total) and never loops forever.

    # (1) pointers, lowest `_pointer_priority` first -- a protected segment's pointer is never
    # dropped ahead of a plain one (same "first claim" rule the earlier pointer selections
    # already use). Cheapest sacrifice: a dropped pointer's item is still recoverable via
    # `expand --list --grep`, unlike a kept item evicted below, which vanishes with no trace
    # at all.
    if len(doc.encode("utf-8")) > max_bytes and shown_elided:
        ranked = sorted(shown_elided, key=_pointer_priority)
        while ranked and len(doc.encode("utf-8")) > max_bytes:
            dropped = ranked.pop(0)
            shown_elided = [it for it in shown_elided if it.id != dropped.id]
            hidden_count += 1
            doc = render(kept_order_list, shown_elided, hidden_count, digest_text)

    # (2) non-owner kept items, lowest priority first, down to a floor of `_NON_OWNER_FLOOR` --
    # coordinator ruling (TRDD-RAEGS1D5, budget floor round 5, on the round 4 regression report):
    # "the at-least-3 non-owner target stands; its purpose is that the resumed session learns
    # what was DONE" (commit aabd8b0c, "jev newest+3"). The floor is checked against
    # `kept_order_list` itself (a running count, not a slice of the eviction list), so it holds
    # even when there were fewer than the floor to begin with -- nothing is ever evicted TO
    # reach the floor, only stopped short of falling below it. `non_owner_evict_order` is built
    # unconditionally (not inside an `if over budget` guard) because stage (4) below reuses
    # whatever this stage did NOT get to pop -- same lowest-priority-first order, continued.
    #
    # In injected mode this is the REVERSE of the non-owner slice of the priority order
    # `kept_order_list` already encodes above (`_select_injected`'s fill order).
    # Every other caller (`--out` never passes `max_item_bytes` in production; this branch only
    # runs under direct test) keeps `evict_key` -- the SAME (protected, max_score, turn)
    # priority the `budget_tokens` eviction above already uses -- not by bare chronological
    # position (review finding, card 5 content-fit): a plain "oldest first" pop would drop an
    # older item ahead of a newer, lower-priority relevance-only one just because it happens to
    # be older. Oldest-among-equal-priority is still the tiebreaker in both, matching the
    # "oldest kept items first" instruction wherever priority does not already decide it.
    if max_item_bytes is not None:
        non_owner_evict_order = list(
            reversed([it for it in kept_order_list if it.kind != "user"])
        )
    else:
        non_owner_evict_order = sorted(
            (it for it in kept_order_list if it.kind != "user"), key=evict_key,
        )
    while (
        non_owner_evict_order
        and len(doc.encode("utf-8")) > max_bytes
        and sum(1 for it in kept_order_list if it.kind != "user") > _NON_OWNER_FLOOR
    ):
        dropped_id = non_owner_evict_order.pop(0).id
        kept_order_list = [it for it in kept_order_list if it.id != dropped_id]
        doc = render(kept_order_list, shown_elided, hidden_count, digest_text)

    # (3) owner-kind kept items, lowest priority first -- reachable only under a hand-built
    # `scores` (production `score_items` never yields one). The floor from (2) is NOT touched
    # here -- deferred to (4), only if this alone is not enough.
    if len(doc.encode("utf-8")) > max_bytes:
        if max_item_bytes is not None:
            owner_tier = [it for it in kept_order_list if it.kind == "user"]
            evict_order = list(reversed(owner_tier))
        else:
            evict_order = sorted(
                (it for it in kept_order_list if it.kind == "user"),
                key=evict_key,
            )
        while evict_order and len(doc.encode("utf-8")) > max_bytes:
            dropped_id = evict_order.pop(0).id
            kept_order_list = [it for it in kept_order_list if it.id != dropped_id]
            doc = render(kept_order_list, shown_elided, hidden_count, digest_text)

    # (4) the remaining non-owner items BELOW the floor -- only reached once (2)+(3) together
    # were not enough. Continues `non_owner_evict_order` (2) already built and stopped partway
    # through -- same lowest-priority-first order, now with no floor at all.
    while non_owner_evict_order and len(doc.encode("utf-8")) > max_bytes:
        dropped_id = non_owner_evict_order.pop(0).id
        kept_order_list = [it for it in kept_order_list if it.id != dropped_id]
        doc = render(kept_order_list, shown_elided, hidden_count, digest_text)

    # (5) the digest, truncated to whatever room remains.
    if len(doc.encode("utf-8")) > max_bytes and digest_text:
        overflow = len(doc.encode("utf-8")) - max_bytes
        digest_bytes = digest_text.encode("utf-8")
        note_bytes = len(_DIGEST_TRUNCATED_NOTE.encode("utf-8"))
        keep = max(0, len(digest_bytes) - overflow - note_bytes)
        digest_text = digest_bytes[:keep].decode("utf-8", "ignore").rstrip() + _DIGEST_TRUNCATED_NOTE
        doc = render(kept_order_list, shown_elided, hidden_count, digest_text)

    if len(doc.encode("utf-8")) > max_bytes:
        # TRDD-RAEGS1D5 (compose() budget floor round 3): every lever above only shrinks the
        # VARIABLE parts -- `render()`'s own fixed lines (embedding `transcript_path` once, in
        # the trailer -- TRDD-EFA4P42B cut the other three copies -- and `full_context_path`
        # once) are never touched by any of it, so they can still be over budget alone once
        # everything else is gone (a long path, or a `max_bytes`
        # this small to begin with -- see `_render_minimal_fallback`'s docstring). This is the
        # function's own hard guarantee: `max_bytes`, when given, is NEVER exceeded -- degrading
        # all the way to `""` rather than ever returning an over-budget string.
        # TRDD-D7RLXAN1: owner messages now arrive in `conversation`, never in `items`, so the
        # newest one comes from there (owner ruling fe38e095 still holds at this last stage).
        conv_owner = [it for it in conversation or [] if it.kind == "user"]
        newest_owner = conv_owner[-1] if conv_owner else None
        doc = _render_minimal_fallback(newest_owner, max_bytes)

    return doc
