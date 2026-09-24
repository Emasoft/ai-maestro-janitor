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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

# WHY: this file lives in scripts/lib/, a sibling of scripts/lib/jevctx/ -- adding this
# directory to sys.path lets `import jevctx...` work whether this module is imported by
# scripts/jev_compact.py (which already does the same insert) or directly by a test that
# never ran that script.
_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import transcript_roles  # noqa: E402  -- needs the sys.path line above; stdlib-only, shared classifier
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
    Noul,
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
    "DECISION_QUESTION",
    "DEFAULT_RELEVANCE_THRESHOLD",
    "DEFAULT_DECISION_THRESHOLD",
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

# The janitor heartbeat protocol's exact quiet reply ("reply with exactly `janitor heartbeat`",
# rules/janitor-heartbeat-protocol.md) -- the one assistant text that carries nothing.
_BARE_HEARTBEAT_REPLY = "janitor heartbeat"

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
    ranks above a relevance-only item in `compose()`'s eviction/pointer-slot ordering, below
    a `decision_passed` one. Always `False` for a non-segmented Item.
    """

    id: str
    kind: ItemKind
    text: str
    tokens: int
    ts: str | None
    turn: int
    protected: bool = False


@dataclass(frozen=True)
class Scores:
    """Both Noul answers for one item, plus the two derived facts callers need.

    `kept`/`oversized` are computed here (not left for `compose` to recompute) because
    `score_items` is the one place that knows the thresholds it used -- `compose`'s
    signature has no threshold parameters, it just trusts these booleans.
    """

    relevance: float
    decision: float
    oversized: bool
    kept: bool
    # Baked in here for the same reason `kept`/`oversized` are: `score_items` is the one
    # place that knows `decision_threshold`. `compose`'s budget eviction reads this to
    # protect a user-stated decision/constraint/correction from being dropped for space
    # before a merely-relevant item is (see `compose`'s eviction-order comment).
    decision_passed: bool
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
) -> tuple[list[Item], list[Item]]:
    """`(conversation, scored)` -- TRDD-D7RLXAN1's enforcement split.

    `conversation`: every LIVE owner/assistant/control item, chronological -- rendered verbatim
    by `compose(conversation=...)`, never scored. `scored`: every tool and event item, before
    and after the boundary -- the only items `score_items` ever sees. Pre-boundary prose that
    was not preserved is in neither list: `window.summary` covers it, and `jev_compact.py expand
    <id>` still resolves it from the raw JSONL."""
    conversation = [it for it in items if it.kind in _CONVERSATION_KINDS and window.is_live(it)]
    scored = [it for it in items if it.kind not in _CONVERSATION_KINDS]
    return conversation, scored


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

# Verbatim per the implementation spec (docs_dev/jev-compaction-spec.md, card 3).
DECISION_QUESTION = Noul(
    instructions=(
        "Is this a decision, constraint, correction or instruction the user stated, "
        "that later work must obey?"
    ),
    true="Yes -- a decision, constraint, correction or instruction the user stated.",
    false="No -- not a decision, constraint, correction or instruction from the user.",
)

DEFAULT_RELEVANCE_THRESHOLD = 0.5
DEFAULT_DECISION_THRESHOLD = 0.5

# Card 5 (TRDD-HWF3QFAB): a "user" item is asked BOTH questions (2 real questions per item,
# so 16 items -- MAX_QUESTIONS_PER_REQUEST // 2 -- fill one 32-question Jev request);
# every other kind is asked relevance only (1 real question per item, so a full 32 items
# fit the same request). Two batch sizes chosen per kind, rather than one shared size that
# always assumes 2 questions per item (the pre-card-5 approach): since "user" items are the
# small minority of a real transcript (report row 7/9: task-notifications alone outnumber
# human messages ~27:1), this roughly halves the batch count -- and with it the digest
# `state` re-billed on every batch -- for the majority of items.
_USER_BATCH_MAX_QUESTIONS = MAX_QUESTIONS_PER_REQUEST // 2
_OTHER_BATCH_MAX_QUESTIONS = MAX_QUESTIONS_PER_REQUEST

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
# halved (5 halvings takes the largest batch this module ever plans, 32 items -- `card 5's
# _OTHER_BATCH_MAX_QUESTIONS` -- down to 1: 32->16->8->4->2->1), and `_MAX_RETRIED_REQUESTS`
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


def _tool_result_text(content: Any) -> str:
    """Text of a `tool_result` block's `content` -- a plain string, or a list of text blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


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

# Card 6: "Protected kinds stacktrace and diff rank above relevance-only items in evict_key,
# below decision_passed" -- see `Item.protected` and `compose()`'s `evict_key`/
# `_pointer_priority`/admission-sort tuples, all of which fold this in as a middle tier.
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
    to `jev_compact.py::_extract_block`, which returns only the RAW tool_result content for a
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
    transcript_path: str | Path, *, segmentation_failures: list[str] | None = None,
    window: ConversationWindow | None = None,
) -> list[Item]:
    """Walk one transcript JSONL and return its extracted, chronologically ordered items.

    `segmentation_failures`, when given, is appended to (in place) with the `item_id_base` of
    every tool result whose segmentation attempt failed and fell back to the pre-card-6 whole
    item -- see `_segment_tool_result`'s own docstring. `None` (the default) costs nothing and
    changes no existing caller's behaviour.

    `window`, when given (TRDD-D7RLXAN1), is filled in place with the LAST compact boundary,
    its preserved uuids and its paired summary -- see `ConversationWindow`. Neither the
    boundary line nor the summary entry ever becomes an item.

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
       heartbeat-protocol reply (`_BARE_HEARTBEAT_REPLY`, TRDD-D7RLXAN1). Real work a
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

    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
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
                        window.summary = _tool_result_text(content)
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
                            result_text = _tool_result_text(block.get("content"))
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
                attachment = entry.get("attachment")
                if not isinstance(attachment, dict) or attachment.get("type") != "queued_command":
                    continue
                # TRDD-RAEGS1D5: `attachment.prompt` is a plain str for a typed message but a
                # list of content blocks (text/image, same shape as `message.content`) when the
                # owner pastes an image alongside text -- measured on the 183 MB c8a95d7e
                # transcript, whose crash was `is_control_input` calling `.strip()` on that
                # list. Reuse `_tool_result_text`, the existing str-or-block-list joiner, rather
                # than assuming str.
                text = _tool_result_text(attachment.get("prompt", ""))
                if not text:
                    continue
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
                        # TRDD-D7RLXAN1: only the BARE quiet reply is dropped, not
                        # `transcript_roles.is_heartbeat_reply`'s wider match (the reply plus up
                        # to two lines). Those lines are drift the owner was shown and the
                        # assistant's own words -- measured on b2bf5b7b, 9 such replies ("The
                        # live account is ...", "The rotation outlook is better than I feared")
                        # vanished from the full copy. Every assistant message is kept intact.
                        if text.strip() == _BARE_HEARTBEAT_REPLY:
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
    asks_decision: bool,
    items_by_id: dict[str, Item],
    digest: str,
    client: JevClient,
    relevance_threshold: float,
    decision_threshold: float,
) -> dict[str, Scores]:
    """Score one batch; the unit `score_items` fans out over a `ThreadPoolExecutor` (card 3,
    TRDD-CC0CZLMO) -- pulled out of the batch loop so each batch's `client.ask()` round trip
    can run on its own worker thread. `items_by_id`/`digest`/`client`/the two thresholds are
    read-only for the whole `score_items` call, so sharing them across threads needs no lock.

    `asks_decision` replaces the old per-item `kind == "user"` check (TRDD-RAEGS1D5 defect 3):
    card 5 (TRDD-HWF3QFAB) groups items by kind into homogeneous batches before this is ever
    called, so every item in one batch shares the same answer -- checking it once per batch
    is simpler and correct by construction (a batch can never mix a "user" item with a
    non-"user" one). A non-"user" item still never gets a `:dec` question sent for it: Jev's
    `state` carries only `{ref, text}` (no author), so asking it there would let that item's
    text alone earn `decision_passed` and `compose`'s eviction protection, defeating the
    question's own point.
    """
    if batch.meta.get("oversized"):
        # Never sent -- fail-open at the library level regardless of caller intent, exactly
        # like jevctx.scorer's own oversized handling. `compose` still refuses to inline it
        # because `oversized=True` here (spec: "never inlined").
        it = items_by_id[batch.items[0].id]
        return {it.id: Scores(relevance=1.0, decision=1.0, oversized=True,
                               kept=False, decision_passed=False)}

    refs = batch.question_keys
    state = _scorer.build_state(digest, batch.items, refs)
    questions: dict[str, Question] = {}
    for ref in refs:
        questions[f"{ref}:rel"] = _scorer._ref_question(RETRIEVE_QUESTION, ref)
        if asks_decision:
            questions[f"{ref}:dec"] = _scorer._ref_question(DECISION_QUESTION, ref)

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
        if asks_decision:
            dec_answer = answers.get(f"{ref}:dec")
            if not isinstance(dec_answer, NoulAnswer):
                raise JevValidationError(
                    f"expected a NoulAnswer for ref {ref!r}, got {type(dec_answer).__name__}"
                )
            dec = dec_answer.value
            decision_passed = dec >= decision_threshold
        else:
            dec = 0.0  # never asked -- see this function's docstring
            decision_passed = False
        kept = rel >= relevance_threshold or decision_passed
        result[it.id] = Scores(relevance=rel, decision=dec, oversized=False,
                                kept=kept, decision_passed=decision_passed)
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
    asks_decision: bool,
    items_by_id: dict[str, Item],
    digest: str,
    client: JevClient,
    relevance_threshold: float,
    decision_threshold: float,
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
                batch, asks_decision=asks_decision, items_by_id=items_by_id, digest=digest,
                client=client, relevance_threshold=relevance_threshold,
                decision_threshold=decision_threshold,
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
                half, asks_decision=asks_decision, items_by_id=items_by_id, digest=digest,
                client=client, relevance_threshold=relevance_threshold,
                decision_threshold=decision_threshold, retry_budget=retry_budget,
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
    decision_threshold: float = DEFAULT_DECISION_THRESHOLD,
    max_workers: int = 8,
    max_split_depth: int = _MAX_SPLIT_DEPTH,
    max_retried_requests: int = _MAX_RETRIED_REQUESTS,
) -> dict[str, Scores]:
    """Score every item against its question(s), batched by kind, fanned out concurrently.

    Sends both questions for a "user" item in ONE request, not two: a review of the first
    draft (two sequential `jevctx.scorer.score_items` calls, one per question) found that
    sends every item's TEXT twice -- once per question's own batch `state` -- doubling
    exactly the cost `jevctx.budget` exists to avoid (Jev bills for `state`, not questions).
    `jevctx.scorer.score_items` has no "two questions per item" mode, so this drives
    `BudgetPlanner` + `client.ask()` directly via `_score_batch` instead.

    Card 5 (TRDD-HWF3QFAB): items are split into two groups BEFORE planning -- `kind ==
    "user"` (both questions, `_USER_BATCH_MAX_QUESTIONS` == 16 items per batch, so the real
    question count never exceeds Jev's 32-per-request cap) and everything else (relevance
    only, `_OTHER_BATCH_MAX_QUESTIONS` == 32 items per batch). Splitting up front -- rather
    than the pre-card-5 approach of planning every item as if it cost 2 questions and only
    skipping the `:dec` one for non-"user" items at send time -- means a transcript's
    overwhelming non-"user" majority (report row 7/9: task-notifications alone outnumber
    human messages ~27:1) now packs twice as many items per request, roughly halving both
    the batch count and the digest `state` re-billed on every one of them.

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
    dec_tokens = estimate_tokens(_scorer._ref_question(DECISION_QUESTION, "i0").to_payload())
    envelope_tokens = estimate_tokens(_scorer.build_state(digest, [], []))

    user_items = [ScoreItem(id=it.id, text=it.text, tokens=it.tokens)
                  for it in items if it.kind == "user"]
    other_items = [ScoreItem(id=it.id, text=it.text, tokens=it.tokens)
                   for it in items if it.kind != "user"]

    user_batches = BudgetPlanner(
        max_questions=_USER_BATCH_MAX_QUESTIONS,
        state_plus_all_questions=_SAFE_STATE_PLUS_ALL_QUESTIONS_TOKENS,
    ).plan(user_items, rel_tokens + dec_tokens, envelope_tokens)
    other_batches = BudgetPlanner(
        max_questions=_OTHER_BATCH_MAX_QUESTIONS,
        state_plus_all_questions=_SAFE_STATE_PLUS_ALL_QUESTIONS_TOKENS,
    ).plan(other_items, rel_tokens, envelope_tokens)
    # (batch, asks_decision) -- the flag that was `items_by_id[...].kind == "user"` per item
    # before card 5 is now decided once per batch, since a batch never mixes the two groups.
    work: list[tuple[Batch, bool]] = (
        [(b, True) for b in user_batches] + [(b, False) for b in other_batches]
    )

    scores: dict[str, Scores] = {}
    blocked_ids: list[str] = []
    retry_budget = _RetryBudget(max_retried_requests)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [
            pool.submit(
                _score_batch_resilient, batch, asks_decision=asks_decision,
                items_by_id=items_by_id, digest=digest, client=client,
                relevance_threshold=relevance_threshold, decision_threshold=decision_threshold,
                retry_budget=retry_budget, origin_index=origin_index,
                max_split_depth=max_split_depth,
            )
            for origin_index, (batch, asks_decision) in enumerate(work)
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
        scores[item_id] = Scores(relevance=0.0, decision=0.0, oversized=False, kept=False,
                                  decision_passed=False, blocked=True)
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
    module already made once for `_format_decision_pointer` below (see its own docstring) --
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


# Coordinator addition (TRDD-RAEGS1D5, full-copy decision-pointer uncap): ~60 chars, not
# `_POINTER_PREVIEW_CHARS`'s 80 -- these lines are UNCAPPED (see `_MAX_ELIDED_POINTERS`'s own
# docstring below), and on the 258 MB transcript ~74% of owner messages pass the decision
# question (28/38 measured on the 49 MB one), so keeping the per-line cost down matters more
# here than for the ordinary, still-capped-at-40 pointer list.
_DECISION_POINTER_PREVIEW_CHARS = 60


def _format_decision_pointer(item: Item) -> str:
    """Compact one-line stand-in for an elided decision-passing owner item, used ONLY for the
    now-uncapped decision pointers in the FULL (`--out`) render (see `_MAX_ELIDED_POINTERS`).
    Just the id and a short preview -- no `tokens=`/`[[elided ...]]` wrapper -- because at
    up to ~185 of these on the 258 MB transcript, the full `_format_pointer` line (id +
    `tokens=N` + an 80-char preview) would cost noticeably more bytes for no added value: the
    model already knows this is a decision item from the section header, it only needs the id
    to `expand` and enough text to recognize which one. Deliberately NOT parsed back by
    `pipeline.find_pointers`/`parse_pointer` (unlike `_format_pointer`'s output) -- nothing
    downstream reads the full document back into `Pointer` objects; `expand <id>` looks the id
    up in the transcript directly, never in this rendered text.
    """
    summary = ""
    for line in item.text.splitlines():
        if line.strip():
            summary = _truncate(line, _DECISION_POINTER_PREVIEW_CHARS)
            break
    return f"{item.id}: {summary}"


# Spec: "Oversized single item (jev marks oversized) -> never inlined; pointer + first 20
# lines" -- a DIFFERENT, richer pointer than a plain budget-dropped item gets (that one is
# just the single-line `_format_pointer` above). An oversized item never even reached Jev
# (jevctx's own budget planner refuses to send it -- see `score_items`), so it has no
# relevance/decision signal at all; the extra 20 lines give the model enough to decide
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
# TRDD-RAEGS1D5 (full-copy decision-pointer uncap): this cap governs only the NON-decision-
# passing elided items in the FULL (`--out`) render -- an elided item that passed the decision
# question is never counted against it there (see `compose()`'s elided-selection code and
# `_format_decision_pointer`). Real data: the 258 MB transcript had 250 decision-passing owner
# items elided-or-kept and only 40 pointer slots total, so 180 of them were reachable by id
# only through `expand --list --grep`, never named in the document the resumed session
# actually reads -- the FULL copy is written to disk precisely so it can afford to name all of
# them. In the injected copy (`--inject-out`, byte-budgeted) this cap likewise governs only the
# ORDINARY pointers; decision pointers come on top of it, bounded by their own byte share
# (`_INJECT_DECISION_POINTER_SHARE`, TRDD-U6C3YXEL) -- see `_select_injected`.
_MAX_ELIDED_POINTERS = 40

# TRDD-RAEGS1D5 (decision-pointer hard ceiling, adversarial-review finding 1 on the
# full-copy decision-pointer uncap above): uncapping `decision_elided` removed the OLD
# unbounded-growth failure (one pointer line per elided item, uncapped, measured ~2.4 MB on
# the largest real transcript -- `_MAX_ELIDED_POINTERS`'s own docstring above) only for
# NON-decision items; `decision_elided` itself had no ceiling at all. On real data ~74% of
# owner messages pass the decision question (28/38 on the 49 MB transcript), so a transcript
# with more, or more decision-dense, owner turns than the 258 MB one measured (214 decision
# pointers, 61 KB) can reproduce that same failure through this new path. Past this many
# elided decision items, the OLDEST are dropped in favor of one summary line -- see
# `compose()`'s elided-selection code -- keeping the newest ones (what the owner said most
# recently matters most on resume), never the highest-scoring: every decision item already
# shares the same top-level `_pointer_priority` tier (`decision_passed=True`), so a score-based
# tiebreak has no more principled claim than recency does.
_MAX_DECISION_POINTERS = 400

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

# TRDD-RAEGS1D5 (orchestrator rebalance): a real run on this repo's own 49 MB and 258 MB
# transcripts showed the injected copy 100% kept="user" (15/15 and 11/11) -- the owner's own
# messages crowded out everything the session actually DID (its assistant replies, tool calls,
# task-notification events). This caps the OWNER group's total byte share -- the newest message
# plus any further owner messages, newest-first with `decision_passed` ones preferred -- at
# `_OWNER_SHARE` of the kept-item budget, so non-user work always gets a real chance at the
# rest. It is a CEILING enforced by a running byte total during selection, never a pre-reserved
# block: a handful of short owner one-liners that do not use the whole share leave the
# remainder to flow to the other tiers, not sit unused (see the selection code below).
_OWNER_SHARE = 0.40

# TRDD-RAEGS1D5 (owner per-item token cap, review of the admission-order fix): the token-level
# counterpart of `DEFAULT_INJECT_ITEM_BYTES`/`NEWEST_OWNER_ITEM_BYTES`, closing a gap those two
# never covered -- `--out` never sets `max_item_bytes`, so its render had NO per-item
# truncation lever at all, and the `budget_tokens` admission below used to admit or evict a
# whole owner item by its FULL token count. Measured on the 258 MB real transcript: owner items
# in the full copy fell from 58 to 45 kept, with only 12 elided pointers surviving the cap --
# a handful of huge owner messages alone consumed the ENTIRE `_OWNER_SHARE` of the budget
# (whole-or-nothing), evicting every OTHER owner item outright -- including decision-passing
# ones -- well before the share was actually spent item-by-item. Every owner item beyond the
# guaranteed newest slot (which stays whole -- see that slot's own comment below) now competes
# for the share as a verbatim-prefix-plus-pointer excerpt capped at this many tokens, the same
# shape `render()` already uses for the byte-capped injected copy, so one big message can no
# longer starve several smaller ones out entirely.
_OWNER_ITEM_TOKEN_CAP = 500


def _owner_item_admission_cost(it: Item) -> tuple[int, bool]:
    """The effective TOKEN cost of admitting `it` beyond compose()'s guaranteed owner slot --
    itself when it already fits `_OWNER_ITEM_TOKEN_CAP`, else the cap PLUS the pointer line's
    own cost (it will render as a verbatim prefix + pointer instead of being admitted or
    evicted whole -- see `_truncate_prefix_tokens` and `_OWNER_ITEM_TOKEN_CAP`'s own docstring
    for why this replaced a plain admit-or-evict decision on the item's full token count).
    Returns `(cost, truncated)`.

    Adversarial review (TRDD-RAEGS1D5): the first version of this function returned exactly
    `_OWNER_ITEM_TOKEN_CAP` for a truncated item, undercounting what `render()` actually prints
    by one `_format_pointer` line -- the byte-tier's own `_inline_cost` (used by the injected
    copy's `_select_injected` candidates) already folds that pointer cost into ITS truncated-item
    cost, so this token-level twin must too, or `admitted_tokens`/`total_tokens` silently drift
    away from what `budget_tokens` is supposed to bound (harmless for `--out` today, since it
    never sets `max_bytes`, but a real inconsistency the "same shape" rationale claims not to
    have).
    """
    if it.tokens <= _OWNER_ITEM_TOKEN_CAP:
        return it.tokens, False
    return _OWNER_ITEM_TOKEN_CAP + estimate_tokens(_format_pointer(it)), True


# TRDD-RAEGS1D5: pointers are breadcrumbs (an id + an 80-char preview), not the content the
# resumed session actually needs -- capping their share of the injected byte budget keeps them
# from crowding out kept items the way the old whole-item eviction let them. 0.15, under the
# "at most 20-25%" ceiling from the card 5 content-fit review: real-data measurement showed the
# FIXED trailer lines this function always emits (header, the "N more items" line, the "Full
# compacted context" trailer -- the transcript path repeated up to 4x) already consume 1.3-1.6
# KB of a 5000-byte budget before a single pointer or kept item is rendered, so reserving the
# full 20-25% for pointers on TOP of that left too little for kept items; 0.15 is still a real
# ceiling on ORDINARY pointers, sized to what real data showed was actually left once the fixed
# cost is measured (`_select_injected`'s `available` measures that cost directly, never guesses
# it). Decision pointers have their own share, below.
_INJECT_POINTER_SHARE = 0.15

# TRDD-U6C3YXEL (decision D2, amendment S2): the injected copy's count line said "681 / 6688 /
# 22709 more" on three real transcripts while 21/22/7 decision-passing owner messages had no
# pointer at all -- the resumed session could not tell they existed. Naming every one is not
# affordable (d30bf250: 28 of them x ~150 B per pointer = its whole 4,230-B room), so the
# NEWEST excluded ones get an ordinary `[[elided id=...]]` pointer up to this share of the
# available bytes and the rest are counted. 0.25, not the advisor's 0.20: S2 kept the ordinary pointer format (it
# parses with `find_pointers`, TRDD-HWF3QFAB, and needs no `render()` change), which is ~45 B
# larger than the compact `id: preview` form the 0.20 was sized for.
_INJECT_DECISION_POINTER_SHARE = 0.25

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

# TRDD-BLGZTHQ9 (amendment S4): the guaranteed owner items were admitted unconditionally at
# `NEWEST_OWNER_ITEM_BYTES` (1,500 B), so on a ~3.9 KB room one long newest message plus the
# newest decision item could leave too little for the non-owner floor, which the old code then
# force-admitted over budget and the backstop evicted again. The newest message's cap is now
# this share of the available bytes (never below the general owner cap `max_item_bytes`, never
# above 1,500 B), and the newest decision item is shown inline only when both together fit in
# `_INJECT_GUARANTEED_SHARE` of it; otherwise it becomes a reserved decision pointer.
_INJECT_NEWEST_OWNER_SHARE = 0.35
_INJECT_GUARANTEED_SHARE = 0.50

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


def _truncate_prefix_tokens(text: str, max_tokens: int) -> str:
    """A VERBATIM prefix of `text` estimated at <= `max_tokens` -- never paraphrased.

    Token-level counterpart of `_truncate_prefix_bytes` (the owner per-item token cap's own
    truncation lever -- see `_OWNER_ITEM_TOKEN_CAP`): `estimate_tokens` has no byte-oriented
    shortcut the way UTF-8 truncation does (a CJK character costs a different token rate than
    a latin one, `jevctx.tokens._estimate_str`), so this binary-searches the CHARACTER cut
    point instead -- the same halving idea `build_digest`'s own single-oversized-part fallback
    already uses, converging in O(log n) calls to `estimate_tokens`. Cuts back to the last
    whole line within that point, same as the byte version, so a truncated item still reads as
    complete lines.
    """
    if estimate_tokens(text) <= max_tokens:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if estimate_tokens(text[:mid]) <= max_tokens:
            lo = mid
        else:
            hi = mid - 1
    prefix = text[:lo]
    nl = prefix.rfind("\n")
    return prefix[:nl] if nl > 0 else prefix


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
    skip-and-continue: a hole inside an exchange reads as a conversation that never happened.
    Returns `(blocks, shown)`: each block costs its UTF-8 length plus the one "\\n" `render()`
    joins it with; `shown` counts the messages among them (markers excluded)."""
    def cost(block: str) -> int:
        return len(block.encode("utf-8")) + 1

    def fits(used: int, c: int) -> bool:
        return budget is None or used + c <= budget

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

    def run_back(start: int, stop_at: int) -> tuple[list[str], int]:
        """Blocks from `start` backward while they fit, newest first; and the first index
        NOT shown (== `stop_at` when every message down to it was)."""
        nonlocal used
        out: list[str] = []
        i = start
        while i > stop_at:
            block = _exchange_block(conversation[i], DEFAULT_INJECT_ITEM_BYTES)
            if not fits(used, cost(block)):
                break
            out.append(block)
            used += cost(block)
            i -= 1
        return out, i

    run, i = run_back(len(conversation) - 1, stop)
    older: list[str] = []
    if owner_block and owner_idx is not None and i == owner_idx:
        # The run reached the owner message, so the exchange is whole from there on: keep
        # going backward past it, still contiguous, while the share lasts (the room would
        # otherwise sit unused whenever the owner spoke last or second-to-last).
        older, _ = run_back(owner_idx - 1, -1)

    blocks: list[str] = list(reversed(older))
    if owner_block and owner_idx is not None:
        blocks.append(owner_block)
        gap = i - owner_idx  # messages after the owner's that the run did not reach
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
    score: float  # max(relevance, decision)
    decision_passed: bool  # only ever True for kind "user" (score_items asks nobody else)
    guaranteed: bool  # one of compose()'s `guaranteed_owner_items`
    inline_cost: int | None  # exact rendered bytes shown inline; None = never inline
    pointer_cost: int  # exact rendered bytes of its `[[elided id=...]]` line(s)
    pointer_eligible: bool  # False for a content-free non-owner item (counted, never pointed)


@dataclass(frozen=True)
class _InjectSelection:
    kept: list[str]  # inline ids, in render order
    pointers: list[str]  # ordinary pointers (at most `max_pointers`)
    decision_pointers: list[str]  # reserved decision pointers, same `[[elided ...]]` format
    hidden: int  # everything else, for the count line


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

    total = 0  # exact bytes of: inline items + the decision reserve + ordinary pointers
    inline_ids: set[str] = set()

    # 1. Guaranteed owner items, the newest message first (owner ruling fe38e095): admitted
    #    unconditionally -- over budget here is the pathological case the backstop handles.
    #    Amendment S4: the newest DECISION item (when different) only if both together fit
    #    `_INJECT_GUARANTEED_SHARE` of the room; otherwise it falls to step 3 as a reserved
    #    decision pointer, so the non-owner floor stays reservable on a ~3.9 KB room.
    guaranteed: list[_InjectCandidate] = []
    for i, c in enumerate(sorted((c for c in cands if c.guaranteed), key=lambda c: c.turn,
                                 reverse=True)):
        if i == 0 or fits(share(_INJECT_GUARANTEED_SHARE), total, inline_cost(c)):
            guaranteed.append(c)
            inline_ids.add(c.id)
            total += inline_cost(c)
    owner_bytes = total

    # 2. The non-owner floor (owner ruling aabd8b0c: "the resumed session learns what was
    #    DONE"), reserved BEFORE the owner tier and never over budget -- met by reservation,
    #    not by overrun plus eviction (the round-5 defect). No `protected` term: a 350-B slice
    #    of a diff must not outrank prose.
    non_owner_order = sorted(
        (c for c in cands if c.kind != "user" and c.inline_cost is not None),
        key=lambda c: (c.decision_passed, c.score, c.turn), reverse=True,
    )
    non_owner: list[_InjectCandidate] = []
    for c in non_owner_order:
        if len(non_owner) >= _NON_OWNER_FLOOR:
            break
        if fits(available, total, inline_cost(c)):
            non_owner.append(c)
            inline_ids.add(c.id)
            total += inline_cost(c)

    # 3. Decision-pointer reserve (TRDD-U6C3YXEL, D2): pointers to the NEWEST not-inline
    #    decision items -- the same newest-first rule `_MAX_DECISION_POINTERS` uses in the full
    #    copy -- within a byte limit fixed HERE: their share, or less if steps 1-2 left less.
    #    WHY the reserve is recomputed around every later admission instead of refunded: the
    #    design's rule gave a reserved item's pointer bytes back to general admission when it
    #    went inline, so steps 4 and 6 drained the reserve -- measured on the four cached real
    #    transcripts, 2/0/2/1 decision pointers (acceptance: at least min(6, excluded)), and 0
    #    on the hand fixture of test_injected_excluded_decision_items_get_newest_first_...;
    #    re-reserving only from leftover room still gave 3/4/8/2. Held, the reserve always
    #    names the newest excluded decision items up to the limit, and an item going inline
    #    hands its place to the next-newest one.
    decision_order = sorted(
        (c for c in cands if c.decision_passed and c.id not in inline_ids),
        key=lambda c: c.turn, reverse=True,
    )
    reserve_limit = (None if available is None
                     else min(int(available * _INJECT_DECISION_POINTER_SHARE), available - total))

    def reserve(also_inline: str = "") -> tuple[list[str], int]:
        ids: list[str] = []
        used = 0
        for c in decision_order:
            if len(ids) >= _MAX_DECISION_POINTERS:
                break
            if (c.id not in inline_ids and c.id != also_inline
                    and fits(reserve_limit, used, c.pointer_cost)):
                ids.append(c.id)
                used += c.pointer_cost
        return ids, used

    reserve_bytes = reserve()[1]
    total += reserve_bytes

    def admit(c: _InjectCandidate) -> bool:
        """Inline `c` if the document still fits with the reserve recomputed around it."""
        nonlocal total, reserve_bytes
        new_reserve = reserve(also_inline=c.id)[1] if c.decision_passed else reserve_bytes
        new_total = total - reserve_bytes + new_reserve + inline_cost(c)
        if available is not None and new_total > available:
            return False
        total, reserve_bytes = new_total, new_reserve
        inline_ids.add(c.id)
        return True

    # 4. Further owner messages, decision-passing first then newest, within `_OWNER_SHARE`.
    #    Excludes a guaranteed decision item step 1 demoted (S4 made it a pointer, not a retry).
    owner_cap = share(_OWNER_SHARE)
    owner_tier: list[_InjectCandidate] = []
    owner_overflow: list[_InjectCandidate] = []
    for c in sorted(
        (c for c in cands if c.kind == "user" and not c.guaranteed and c.inline_cost is not None),
        key=lambda c: (c.decision_passed, c.turn), reverse=True,
    ):
        if fits(owner_cap, owner_bytes, inline_cost(c)) and admit(c):
            owner_tier.append(c)
            owner_bytes += inline_cost(c)
        else:
            owner_overflow.append(c)

    # 5. Non-owner items beyond the floor, same order as step 2.
    non_owner += [c for c in non_owner_order if c.id not in inline_ids and admit(c)]

    # 6. One more try for the owner overflow, without the share cap.
    rescued = [c for c in owner_overflow if admit(c)]

    # 7. Ordinary pointers (amendment S1: every item not inline -- elided by the token stage or
    #    excluded here), highest score first, capped by count (`max_pointers`, S8: decision
    #    pointers come on top) and by `_INJECT_POINTER_SHARE`. Decision items are step 3's.
    pointer_cap = share(_INJECT_POINTER_SHARE)
    pointers: list[str] = []
    pointer_bytes = 0
    for c in sorted(
        (c for c in cands
         if c.id not in inline_ids and c.pointer_eligible and not c.decision_passed),
        key=lambda c: c.score, reverse=True,
    ):
        if len(pointers) >= max_pointers:
            break
        if fits(pointer_cap, pointer_bytes, c.pointer_cost) and fits(available, total,
                                                                     c.pointer_cost):
            pointers.append(c.id)
            pointer_bytes += c.pointer_cost
            total += c.pointer_cost

    kept = [c.id for c in (*guaranteed, *owner_tier, *non_owner, *rescued)]
    decision_pointers = reserve()[0]
    # TRDD-U6C3YXEL: the count line names EVERYTHING not shown -- it used to omit every byte-
    # stage exclusion, so "681 more" hid 21 decision-passing owner messages.
    hidden = len(cands) - len(kept) - len(pointers) - len(decision_pointers)
    return _InjectSelection(kept=kept, pointers=pointers, decision_pointers=decision_pointers,
                            hidden=hidden)


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
    fixed trailing "expand with" line -- never inside an individual pointer. Sole exception:
    the "N more decision items" summary line further below can ALSO embed it, but only in the
    FULL (`--out`) render, and only past `_MAX_DECISION_POINTERS` (400) elided decision items --
    `decision_elided` is forced empty whenever `max_item_bytes is not None`, so the injected
    copy (the one this fix's byte budget is about) never triggers that line at all.

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
      (3) evict NON-GUARANTEED-OWNER kept items (`kind == "user"`, excluding the two guaranteed
          slots below), lowest priority first;
      (4) only once (2)+(3) together are still not enough, come back for the last
          `_NON_OWNER_FLOOR` non-owner items -- the SAME lowest-priority-first order (2) already
          computed and stopped partway through, now continued with no floor;
      (5) truncate the digest text itself;
      (6) the newest DECISION item -- the second guaranteed slot (owner ruling, commit
          aabd8b0c) -- sacrificed on its own, distinct from (2)-(4), only once (1)-(5) are still
          not enough, and only when it differs from the newest owner message.
    When `max_item_bytes` is unset (TRDD-RAEGS1D5: the `budget_tokens` eviction above now admits
    by an owner-share-capped order instead, but this narrower byte-only fallback keeps
    `evict_key`'s plain (decision_passed, max_score) rule for (2)-(4), unchanged) -- lowest
    first, oldest among ties -- never bare chronological order, so a decision-passed item (a
    user instruction/correction) is not sacrificed ahead of a newer, lower-priority one just for
    being older. The trailing "pointers expand with:" line is NEVER dropped by stages (1)-(6) --
    it is the model's only way back to everything elided, and a blind `raw[:room]` slice
    downstream (`external_clear.compose_handoff`, before an earlier fix) used to cut it off
    along with the newest kept items because both sit at the tail of the joined string.

    (7) the SOLE exception (TRDD-RAEGS1D5, budget floor round 3): `render()`'s own fixed lines
    -- header, section headings, that same trailing line -- embed `transcript_path` (TRDD-
    EFA4P42B: once, in the trailer, since the header/elided-line/full-context-line copies were
    removed) and `full_context_path` once, so stages (1)-(6) alone cannot guarantee the fixed
    skeleton itself fits a small `max_bytes` or survives a long transcript path. Only once
    (1)-(6) still leave the render over budget, the ENTIRE document -- trailer included -- is
    replaced by `_render_minimal_fallback`'s constant-size marker plus the newest OWNER message
    (`guaranteed_owner_items[0]`, the FIRST guaranteed slot) truncated to whatever room remains,
    or `""` when nothing fits at all -- the one item no stage above ever sacrifices, per the
    owner ruling "the owner's newest message first" (fe38e095) -- it is dropped LAST, if at
    all. This is the function's actual, load-bearing guarantee: `max_bytes`, when given, is
    NEVER exceeded by the return value, not merely "usually" or "in the common case" above.

    Within the `budget_tokens` admission itself (TRDD-RAEGS1D5, owner per-item token cap): an
    owner item beyond the one guaranteed slot is admitted at its capped cost
    (`_OWNER_ITEM_TOKEN_CAP`, `_owner_item_admission_cost`), rendering as a verbatim prefix plus
    a pointer when it is over that cap, rather than an all-or-nothing admit/evict decision on
    its full size -- see that constant's own docstring for the real-transcript defect this
    fixes. An owner item that still does not fit at all, even capped, becomes an ordinary
    elided pointer, but `decision_passed` ones get first claim on the limited pointer slots
    over any merely-relevant item (`_pointer_priority`, used everywhere this function ranks or
    trims the elided-pointer list) -- a stated decision the user gave is never silently
    unreachable just because the item that carried it did not fit inline. In the FULL
    (`--out`) render specifically (`max_item_bytes is None`), this goes further: every elided
    `decision_passed` item gets a pointer, essentially uncapped -- `max_elided_pointers` governs
    only the remaining, non-decision-passing elided items there (see `_MAX_ELIDED_POINTERS`'s
    own docstring for the real-transcript defect this closes). It renders as a compact
    `id: preview` line (`_format_decision_pointer`), not the ordinary `_format_pointer` shape,
    to keep the size growth from potentially hundreds of extra lines down. Past
    `_MAX_DECISION_POINTERS` (400) even that list is bounded -- the newest survive, the rest
    fold into one summary line (see that constant's own docstring for why an unbounded
    decision-pointer list would reproduce the exact failure `_MAX_ELIDED_POINTERS` exists to
    prevent). The injected copy selects its own pointers -- see `max_item_bytes` below.

    `max_item_bytes`, when given (the injected copy; `--out` never passes it): after the shared
    `budget_tokens` stage, what is shown inline, what gets a pointer and what is only counted is
    decided by `_select_injected` (TRDD-BLGZTHQ9 + TRDD-U6C3YXEL), which fits the render to
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
    # Oversized is re-checked here, not just trusted from `scores[...].kept`, because
    # "never inlined" is the compose-time invariant the spec actually cares about -- this
    # function is where inlining happens, so this is where the guard has to hold even if a
    # caller builds `scores` by hand (as the tests do) instead of via `score_items`.
    kept_items = [
        it for it in items if scores[it.id].kept and not scores[it.id].oversized
    ]

    # TRDD-RAEGS1D5 (jev newest+3, owner ruling fe38e095 "the owner's newest message first"):
    # the chronologically newest owner (`kind == "user"`) item is admitted UNCONDITIONALLY,
    # regardless of Jev's own kept/oversized gate -- card 6's own disclosure (TRDD-88DOI824)
    # found `guaranteed_owner_items` below silently dropped it whenever Jev itself scored it
    # below threshold: measured on the 258 MB transcript, item `92828da9...` (the transcript's
    # chronologically last owner message, content "resume") scored relevance=0.29,
    # decision=0.22, both under the 0.5 default thresholds, so `kept=False` and it never
    # reached `kept_items` at all. Excludes only an `oversized` item -- its raw text was never
    # even sent to Jev, and this function's own "never inlined" invariant (see
    # `_oversized_preview`) must still hold for it; a `blocked` item (never scored, e.g. a
    # provider firewall block) is NOT excluded -- its text is intact, and "whatever its score"
    # includes "no score at all". Force-added to `kept_items` ITSELF (not just to
    # `guaranteed_owner_items` below) so every downstream consumer -- `total_tokens`,
    # `kept_ids`, `elided_items`, the `budget_tokens` eviction branch -- treats it uniformly
    # with an item Jev actually kept, instead of needing its own special case at each site.
    _newest_owner_ever = next(
        (
            it for it in sorted(items, key=lambda it: it.turn, reverse=True)
            if it.kind == "user" and not scores[it.id].oversized
        ),
        None,
    )
    if _newest_owner_ever is not None and _newest_owner_ever.id not in {
        it.id for it in kept_items
    }:
        kept_items = kept_items + [_newest_owner_ever]

    def max_score(it: Item) -> float:
        s = scores[it.id]
        return max(s.relevance, s.decision)

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
    # this change): `score_items` gives an oversized item relevance=1.0/decision=1.0 and
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

    def evict_key(it: Item) -> tuple[bool, bool, float, int]:
        # (decision_passed, protected, max_score, turn) ascending: a relevance-only item
        # (`False`, `False`) sorts, and is dropped, BEFORE any item that passed the decision
        # question -- "never let the budget undo the decision question" (a user-stated
        # decision, constraint, correction or instruction the user gave later work must obey
        # is worse to lose than merely-relevant background). Card 6 (TRDD-88DOI824): a
        # `protected` segment (stacktrace/diff, see `Item.protected`) sits in its own tier
        # between the two -- it is structurally important even when Jev scores it as
        # merely-relevant, but never outranks an actual stated decision. Within each tier,
        # lowest score first, oldest (smallest `turn`) among equal scores. `_effective_
        # protected` (not the raw `it.protected`), per the "at most one segment per source
        # item" cap above.
        return (scores[it.id].decision_passed, _effective_protected(it), max_score(it), it.turn)

    # TRDD-RAEGS1D5 (orchestrator rebalance) + coordinator ruling: TWO owner items are
    # guaranteed a slot, uncapped, ahead of every per-item cap -- the chronologically newest
    # owner message (by `turn`, unconditionally) AND the newest `decision_passed` owner item
    # (if one exists and differs from the first; they may be the same item, in which case
    # there is only one). Commit d4fa7685 narrowed the ORIGINAL single guaranteed slot to
    # "newest decision-passing, else newest plain", which silently dropped the genuinely
    # newest owner message whenever an OLDER decision-passing one existed (measured on the
    # 258 MB transcript: item id `92828da9...`, the chronologically newest owner message, was
    # absent from both the full and the injected copy) -- reintroducing, in the opposite
    # direction, the same class of bug the pre-d4fa7685 "always newest" rule had (see
    # `test_guaranteed_owner_slot_prefers_newest_decision_passed_over_newest_plain`'s own
    # docstring/history for that earlier failure mode). Both guaranteed items now coexist:
    # neither displaces the other.
    #
    # Computed here, from `kept_items` (BEFORE any eviction), because BOTH consumers need it
    # regardless of whether `total_tokens > budget_tokens` ever triggers eviction below: the
    # admission branch force-admits these ids at FULL size (never `_owner_item_admission_
    # cost`-capped), and `render`'s per-item cap check (closing over this name) gives them
    # `NEWEST_OWNER_ITEM_BYTES` instead of the general `max_item_bytes` in the injected copy
    # even when NOTHING was evicted at the token level -- the byte-capped render is a
    # separate, independent budget from `budget_tokens`. `kept_items` was already extended
    # above (jev newest+3) with the unconditionally-guaranteed newest owner item when Jev
    # itself did not keep it, so `owner_kept_all[0]` below is genuinely the newest owner item
    # in `items`, not merely the newest one Jev happened to keep.
    owner_kept_all = sorted(
        (it for it in kept_items if it.kind == "user"), key=lambda it: it.turn, reverse=True,
    )
    guaranteed_owner_items: list[Item] = []
    if owner_kept_all:
        guaranteed_owner_items.append(owner_kept_all[0])  # newest owner message, always
        newest_decision_owner_item = next(
            (it for it in owner_kept_all if scores[it.id].decision_passed), None,
        )
        if (newest_decision_owner_item is not None
                and newest_decision_owner_item.id != owner_kept_all[0].id):
            guaranteed_owner_items.append(newest_decision_owner_item)
    guaranteed_owner_ids: set[str] = {it.id for it in guaranteed_owner_items}
    # TRDD-RAEGS1D5 (owner per-item token cap): item id -> the `_OWNER_ITEM_TOKEN_CAP` it was
    # truncated to during the `budget_tokens` admission below -- declared here for the same
    # reason `guaranteed_owner_ids` is (`render` closes over it and needs a name regardless of
    # whether that admission branch ever runs). Empty means every kept item renders in full;
    # only `--out` (which never sets `max_item_bytes`) actually reaches this in `render` --
    # the injected copy's own byte cap is always tighter and fires first, see `render`'s
    # per-item cap check.
    token_truncated: dict[str, int] = {}

    total_tokens = sum(it.tokens for it in kept_items)
    kept_ids = {it.id for it in kept_items}
    if total_tokens > budget_tokens:
        # TRDD-RAEGS1D5 (release blocker): admit by an owner-share-capped priority order
        # instead of the old plain `evict_key` removal loop. `evict_key`'s (decision_passed,
        # max_score, turn) ascending sort dropped every non-`decision_passed` item BEFORE any
        # `decision_passed` one, no matter how relevant -- and `decision_passed` can only
        # ever be True for a "user" item (`DECISION_QUESTION` above is never sent to any
        # other kind). Measured on this repo's own 49 MB transcript (d30bf250,
        # reports/compaction-replacement/): its 28 `decision_passed` "user" items alone
        # total 14298 tokens, already over the 8000-token default `budget_tokens`, so every
        # one of the 158 relevance-passing tool/assistant/event items (of 4141/1725/171
        # scored) was evicted first and NONE survived -- a resumed session then only ever
        # saw what the owner asked, never what was done. This mirrors the byte-tier
        # owner-share ceiling (`_OWNER_SHARE`) below at the TOKEN level, so the FULL
        # (`--out`) rendering -- which never sets `max_item_bytes` and so never reaches that
        # byte tier -- gets the same guarantee as the injected copy, not a narrower one.
        #
        # TRDD-RAEGS1D5 (owner per-item token cap, review of this admission order): beyond the
        # guaranteed slot, each owner item competes for the SHARE at its capped cost
        # (`_owner_item_admission_cost`), not its full size -- an admit-whole-or-evict-whole
        # decision on the full token count let a HANDFUL of huge owner messages consume the
        # entire share themselves (measured on the 258 MB transcript: 58 owner items kept fell
        # to 45), evicting every other owner item outright, decision-passing ones included,
        # long before the share was actually spent. A capped item still costs its slot in the
        # share and renders as a verbatim prefix + pointer (`token_truncated` below) instead of
        # disappearing whole.
        # `owner_kept_all`/`guaranteed_owner_items`/`guaranteed_owner_ids` were computed above
        # `render`'s own name lookup, from `kept_items` -- reused here unchanged (same filter,
        # same order) rather than recomputed, so the admission decision and the render-cap
        # exemption can never disagree about which ids are guaranteed.
        owner_kept = owner_kept_all
        admitted: list[Item] = []
        admitted_tokens = 0
        for guaranteed_it in guaranteed_owner_items:
            admitted.append(guaranteed_it)
            admitted_tokens += guaranteed_it.tokens
        rest_of_owner_kept = [it for it in owner_kept if it.id not in guaranteed_owner_ids]
        owner_token_budget = int(budget_tokens * _OWNER_SHARE)
        token_owner_overflow: list[Item] = []
        for it in sorted(
            rest_of_owner_kept,
            key=lambda it: (scores[it.id].decision_passed, it.turn), reverse=True,
        ):
            cost, truncated = _owner_item_admission_cost(it)
            if admitted_tokens + cost > owner_token_budget:
                token_owner_overflow.append(it)  # may still fit once non-owner items are placed
                continue
            admitted.append(it)
            admitted_tokens += cost
            if truncated:
                token_truncated[it.id] = _OWNER_ITEM_TOKEN_CAP
        for it in sorted(
            (it for it in kept_items if it.kind != "user"),
            # Card 6 (TRDD-88DOI824): `_effective_protected(it)` (stacktrace/diff, capped to
            # one segment per source item -- see that helper's own comment) slots in between
            # `decision_passed` and plain relevance -- same tier as `evict_key`/
            # `_pointer_priority` above, so a structurally-important segment is not starved
            # out of the budget by a merely-more-relevant sibling.
            key=lambda it: (
                scores[it.id].decision_passed, _effective_protected(it), max_score(it), it.turn,
            ),
            reverse=True,
        ):
            if admitted_tokens + it.tokens > budget_tokens:
                continue  # a smaller lower-priority item further down may still fit
            admitted.append(it)
            admitted_tokens += it.tokens
        for it in token_owner_overflow:
            # TRDD-RAEGS1D5: still capped, not restored to full size -- an item that did not
            # fit the owner share even truncated gets the SAME capped shot at the leftover
            # general budget, never a second chance to be admitted whole.
            cost, truncated = _owner_item_admission_cost(it)
            if admitted_tokens + cost > budget_tokens:
                continue
            admitted.append(it)
            admitted_tokens += cost
            if truncated:
                token_truncated[it.id] = _OWNER_ITEM_TOKEN_CAP
        kept_ids = {it.id for it in admitted}
        total_tokens = admitted_tokens

    def _pointer_priority(it: Item) -> tuple[bool, bool, float]:
        # TRDD-RAEGS1D5 (owner per-item token cap, requirement 1): "evicted decision-passing
        # items get first claim on the pointer slots" -- an owner item the budget admission
        # above could not fit even truncated (see `token_truncated`) still names a decision,
        # constraint or correction the user gave; it must not lose its one remaining pointer
        # slot to a merely-relevant item just because the latter scores marginally higher.
        # Card 6 (TRDD-88DOI824): a `protected` segment (stacktrace/diff) gets the same
        # middle-tier claim `evict_key` gives it -- same rationale, same ordering; capped to
        # one segment per source item, per `_effective_protected`'s own comment.
        return (scores[it.id].decision_passed, _effective_protected(it), max_score(it))

    # TRDD-BLGZTHQ9 (amendment S4): the per-item cap `render()` gives BOTH guaranteed owner
    # items in the injected copy. `NEWEST_OWNER_ITEM_BYTES` until the injected selection below
    # shrinks it to its share of the room; it has to be a name `render()` reads at call time
    # (not a render() argument) because every later render -- the backstop's included -- must
    # use the same cap the selection costed, or the exact-fit arithmetic breaks.
    guaranteed_item_cap = NEWEST_OWNER_ITEM_BYTES

    transcript_path = header.get("transcript_path", "")
    usage = header.get("usage") or {}
    # Shared by both "N more not listed" summary lines below (the pre-existing one and the
    # decision-ceiling one) -- same underlying `expand --list` command either way, so it is
    # built once instead of twice.
    expand_list_cmd = (
        'uv run --script "$CLAUDE_PLUGIN_ROOT/scripts/jev_compact.py" expand --transcript '
        f"{transcript_path} --list --grep TEXT"
    )

    # TRDD-D7RLXAN1: the conversation section and the READ FIRST line -- FIXED text for render(),
    # which reads both names at call time. Filled in below, after the injected render's baseline
    # without them is measured (the exchange budget is a share of the room that baseline leaves).
    conversation_lines: list[str] = []
    read_first = ""

    def render(
        kept_order: list[Item], elided: list[Item], hidden: int, digest_text: str,
        decision_hidden: int = 0,
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
            # TRDD-RAEGS1D5 (orchestrator rebalance) + coordinator ruling: BOTH guaranteed
            # owner items (the newest message, and the newest decision-passing one when it
            # differs -- see `guaranteed_owner_ids`'s own docstring above) get the larger
            # `guaranteed_item_cap` (`NEWEST_OWNER_ITEM_BYTES`, or its share of the room once
            # the injected selection sets it) instead of the general `max_item_bytes` -- this
            # includes the unconditionally-guaranteed newest owner item added above even when
            # Jev itself never kept it (coordinator addition: "stays capped at the existing
            # 1,500-byte newest-owner limit... prefix plus pointer beyond that"). A non-owner
            # item, when `non_owner_item_bytes` is given, gets ITS OWN (smaller) cap instead
            # of `max_item_bytes` -- see that parameter's own docstring; every OTHER owner
            # item keeps `max_item_bytes` unchanged.
            cap = (
                guaranteed_item_cap
                if max_item_bytes is not None and it.id in guaranteed_owner_ids
                else (
                    non_owner_item_bytes
                    if (
                        max_item_bytes is not None
                        and non_owner_item_bytes is not None
                        and it.kind != "user"
                    )
                    else max_item_bytes
                )
            )
            if max_item_bytes is not None and cap is not None and _is_task_notification(it):
                # TRDD-BLGZTHQ9 addendum: injected-only (max_item_bytes is not None) -- the
                # `--out` render (max_item_bytes is None) must stay byte-identical, so it never
                # takes this branch and keeps showing `it.text` whole below.
                block, _, _ = _notification_block(it, cap)
                lines.append(block)
                continue
            text_bytes = it.text.encode("utf-8")
            token_cap = token_truncated.get(it.id)
            if cap is not None and len(text_bytes) > cap:
                # TRDD-RAEGS1D5 requirement 2: a verbatim prefix, never a paraphrase, plus a
                # pointer back to the rest -- see `_truncate_prefix_bytes`'s own docstring for
                # why this is what stops one oversized-relative-to-budget item from being
                # evicted whole the way the old byte backstop did.
                lines.append(_truncate_prefix_bytes(it.text, cap))
                lines.append(_format_pointer(it))
            elif token_cap is not None:
                # TRDD-RAEGS1D5 (owner per-item token cap): the `--out` rendering never sets
                # `max_item_bytes`, so the branch above never fires for it -- this is its own
                # verbatim-prefix-plus-pointer lever, populated only for an owner item the
                # `budget_tokens` admission above capped rather than admitted whole (see
                # `_OWNER_ITEM_TOKEN_CAP`). For the injected copy the byte cap is always
                # tighter (700-1500 B, well under this cap's ~1750-char worth), so the branch
                # above fires first there and this one is effectively `--out`-only.
                lines.append(_truncate_prefix_tokens(it.text, token_cap))
                lines.append(_format_pointer(it))
            else:
                lines.append(it.text)

        lines.append("")
        lines.append("## Elided")
        elided_ids = {it.id for it in elided}
        for it in items:
            if it.id in elided_ids:
                # TRDD-RAEGS1D5 (full-copy decision-pointer uncap): a decision-passing item
                # is never oversized or blocked (`score_items` sets `decision_passed=False`
                # on both paths -- see their own Scores construction), so the compact line is
                # always the whole story for it; nothing below this branch ever applies.
                if max_item_bytes is None and scores[it.id].decision_passed:
                    lines.append(_format_decision_pointer(it))
                    continue
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
        if decision_hidden:
            # TRDD-RAEGS1D5 (decision-pointer hard ceiling): the `_MAX_DECISION_POINTERS`
            # trim's own summary line -- the OLDEST decision items past the ceiling, never
            # named individually (see that constant's docstring for why), still reachable by
            # the same `expand --list` command the "more items not listed" line below uses.
            lines.append(
                f"... and {decision_hidden} more decision items: run `{expand_list_cmd}` "
                "to list them"
            )
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
        if available is not None:
            # Amendment S4: never above 1,500 B, never below the general owner cap (a room too
            # small for 35% of it to hold even an ordinary owner item is the backstop's case).
            guaranteed_item_cap = min(
                NEWEST_OWNER_ITEM_BYTES,
                max(max_item_bytes, int(available * _INJECT_NEWEST_OWNER_SHARE)),
            )
        non_owner_cap = non_owner_item_bytes if non_owner_item_bytes is not None else max_item_bytes
        cands: list[_InjectCandidate] = []
        for it in items:
            s = scores[it.id]
            # Mirrors render()'s "## Elided" branch: pointer line, plus the firewall note for a
            # blocked item (the oversized preview is --out only).
            pointer_cost = len(_format_pointer(it).encode("utf-8")) + 1
            if s.blocked and not s.oversized:
                pointer_cost += len("unscored (provider firewall)") + 1
            if it.kind == "user":
                cap = guaranteed_item_cap if it.id in guaranteed_owner_ids else max_item_bytes
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
                inline_ok = (it.id in kept_ids and pointer_eligible
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
                # 0.18s" survives), 80 for prose/events and for any truncated prefix.
                min_chars = (_INJECT_MIN_WHOLE_TOOL_BODY_CHARS if whole and it.kind == "tool"
                             else _INJECT_MIN_BODY_CHARS)
                pointer_eligible = _body_chars(gate_body) >= min_chars
                # TRDD-BLGZTHQ9: a tool result over the cap is a pointer, never a prefix -- the
                # pointer's preview already says WHAT it is, and a 350-B slice of a diff/grep/
                # Bash result added a few lines for 3-4x the bytes (all 7 truncated tool items
                # measured in the three real injected copies). Prose reads fine as a prefix.
                inline_ok = (it.id in kept_ids and pointer_eligible
                             and (whole or it.kind != "tool"))
                inline_cost = _inline_cost(it, non_owner_cap) if inline_ok else None
            cands.append(_InjectCandidate(
                id=it.id, kind=it.kind, turn=it.turn, score=max_score(it),
                decision_passed=s.decision_passed, guaranteed=it.id in guaranteed_owner_ids,
                inline_cost=inline_cost, pointer_cost=pointer_cost,
                pointer_eligible=pointer_eligible,
            ))
        selection = _select_injected(cands, available=available,
                                     max_pointers=max_elided_pointers)
        by_id = {it.id: it for it in items}
        kept_order_list = [by_id[i] for i in selection.kept]
        # render() walks `items` for the "## Elided" list, so pointers stay chronological.
        shown_elided = [by_id[i] for i in (*selection.pointers, *selection.decision_pointers)]
        hidden_count = selection.hidden
        decision_hidden_count = 0
    else:
        # `items` is already chronological, so filtering it (rather than re-sorting) keeps the
        # elided list chronological for free -- `max_elided_pointers` below only needs to pick
        # WHICH ids survive, not reorder anything.
        elided_items = [it for it in items if it.id not in kept_ids]
        hidden_count = 0

        # TRDD-RAEGS1D5 (full-copy decision-pointer uncap): in the FULL render only
        # (`max_item_bytes is None` -- the injected copy always passes it, see `render`'s per-item
        # cap check elsewhere in this function), split off every elided decision-passing item
        # BEFORE the cap is applied, so it is never competing for one of `max_elided_pointers`
        # slots at all -- `decision_passed` can only ever be True for a "user"/owner item
        # (`score_items` only ever asks the decision question of a "user" batch), so this already
        # selects exactly "elided decision-passing owner item". `_MAX_ELIDED_POINTERS`'s own
        # docstring above has the real-data motivation.
        decision_elided = [it for it in elided_items if scores[it.id].decision_passed]
        other_elided = [it for it in elided_items if not scores[it.id].decision_passed]

        # TRDD-RAEGS1D5 (decision-pointer hard ceiling): see `_MAX_DECISION_POINTERS`'s own
        # docstring for why this exists. Newest-first, unlike `_pointer_priority` elsewhere in
        # this function -- every item here already shares one priority tier (decision_passed),
        # so recency is what actually distinguishes them for a resumed session.
        decision_hidden_count = 0
        if len(decision_elided) > _MAX_DECISION_POINTERS:
            newest_first = sorted(decision_elided, key=lambda it: it.turn, reverse=True)
            shown_decision = newest_first[:_MAX_DECISION_POINTERS]
            decision_hidden_count = len(decision_elided) - len(shown_decision)
        else:
            shown_decision = decision_elided

        if len(other_elided) > max_elided_pointers:
            # Highest priority first -- decision_passed items before any non-decision one,
            # highest max(relevance, decision) as the tiebreak -- the items most worth a pointer
            # are the ones the model was closest to keeping, not an arbitrary chronological
            # head/tail.
            top_ids = {
                it.id
                for it in sorted(other_elided, key=_pointer_priority, reverse=True)[:max_elided_pointers]
            }
            shown_other = [it for it in other_elided if it.id in top_ids]
            hidden_count = len(other_elided) - len(shown_other)
        else:
            shown_other = other_elided
        shown_elided = shown_decision + shown_other
        kept_order_list = [it for it in items if it.id in kept_ids]  # `items` is chronological

    doc = render(kept_order_list, shown_elided, hidden_count, digest_text, decision_hidden_count)
    if max_bytes is None or len(doc.encode("utf-8")) <= max_bytes:
        return doc

    # Backstop degrade, in priority order -- see the docstring for the full rationale (round 5
    # coordinator ruling, on the round 4 regression report). Each step only runs if the
    # previous ones were not enough; lists are popped from one end so this is bounded (at most
    # `len(items)` iterations total) and never loops forever.

    # (1) pointers, lowest `_pointer_priority` first -- ties broken by lowest score, but a
    # decision_passed pointer is never dropped ahead of a non-decision one (same "first claim"
    # rule the two earlier pointer selections already use). Cheapest sacrifice: a dropped
    # pointer's item is still recoverable via `expand --list --grep`, unlike a kept item
    # evicted below, which vanishes with no trace at all.
    if len(doc.encode("utf-8")) > max_bytes and shown_elided:
        ranked = sorted(shown_elided, key=_pointer_priority)
        while ranked and len(doc.encode("utf-8")) > max_bytes:
            dropped = ranked.pop(0)
            shown_elided = [it for it in shown_elided if it.id != dropped.id]
            hidden_count += 1
            doc = render(kept_order_list, shown_elided, hidden_count, digest_text, decision_hidden_count)

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
    # runs under direct test) keeps `evict_key` -- the SAME (decision_passed, max_score, turn)
    # priority the `budget_tokens` eviction above already uses -- not by bare chronological
    # position (review finding, card 5 content-fit): a plain "oldest first" pop would drop a
    # decision-passed item (a user instruction/correction the budget eviction deliberately
    # protects) ahead of a newer, lower-priority relevance-only item just because it happens to
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
        doc = render(kept_order_list, shown_elided, hidden_count, digest_text, decision_hidden_count)

    # (3) non-guaranteed-owner kept items, lowest priority first -- `guaranteed_owner_items` (the
    # newest owner message, always, plus the newest decision item when it differs) is excluded;
    # see (6) and the terminal stage below for when either of those two is ever sacrificed. The
    # floor from (2) is NOT touched here -- deferred to (4), only if this alone is not enough.
    if len(doc.encode("utf-8")) > max_bytes:
        if max_item_bytes is not None:
            non_guaranteed_owner_tier = [
                it for it in kept_order_list
                if it.kind == "user" and it.id not in guaranteed_owner_ids
            ]
            evict_order = list(reversed(non_guaranteed_owner_tier))
        else:
            evict_order = sorted(
                (
                    it for it in kept_order_list
                    if it.kind == "user" and it.id not in guaranteed_owner_ids
                ),
                key=evict_key,
            )
        while evict_order and len(doc.encode("utf-8")) > max_bytes:
            dropped_id = evict_order.pop(0).id
            kept_order_list = [it for it in kept_order_list if it.id != dropped_id]
            doc = render(kept_order_list, shown_elided, hidden_count, digest_text, decision_hidden_count)

    # (4) the remaining non-owner items BELOW the floor -- only reached once (2)+(3) together
    # were not enough. Continues `non_owner_evict_order` (2) already built and stopped partway
    # through -- same lowest-priority-first order, now with no floor at all.
    while non_owner_evict_order and len(doc.encode("utf-8")) > max_bytes:
        dropped_id = non_owner_evict_order.pop(0).id
        kept_order_list = [it for it in kept_order_list if it.id != dropped_id]
        doc = render(kept_order_list, shown_elided, hidden_count, digest_text, decision_hidden_count)

    # (5) the digest, truncated to whatever room remains.
    if len(doc.encode("utf-8")) > max_bytes and digest_text:
        overflow = len(doc.encode("utf-8")) - max_bytes
        digest_bytes = digest_text.encode("utf-8")
        note_bytes = len(_DIGEST_TRUNCATED_NOTE.encode("utf-8"))
        keep = max(0, len(digest_bytes) - overflow - note_bytes)
        digest_text = digest_bytes[:keep].decode("utf-8", "ignore").rstrip() + _DIGEST_TRUNCATED_NOTE
        doc = render(kept_order_list, shown_elided, hidden_count, digest_text, decision_hidden_count)

    # (6) the newest DECISION item -- the second guaranteed slot (owner ruling, commit
    # aabd8b0c) -- sacrificed on its own, distinct from (2)-(4), only once the digest is
    # already spent and only when it still differs from the newest owner message (an empty
    # `guaranteed_owner_items[1:]` means there is nothing here to drop).
    if len(doc.encode("utf-8")) > max_bytes and len(guaranteed_owner_items) > 1:
        decision_id = guaranteed_owner_items[1].id
        if any(it.id == decision_id for it in kept_order_list):
            kept_order_list = [it for it in kept_order_list if it.id != decision_id]
            doc = render(kept_order_list, shown_elided, hidden_count, digest_text, decision_hidden_count)

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
        newest_owner = (conv_owner[-1] if conv_owner
                        else guaranteed_owner_items[0] if guaranteed_owner_items else None)
        doc = _render_minimal_fallback(newest_owner, max_bytes)

    return doc
