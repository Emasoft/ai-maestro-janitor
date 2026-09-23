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
from jevctx.tokens import estimate_tokens  # noqa: E402
from jevctx.types import (  # noqa: E402
    MAX_QUESTIONS_PER_REQUEST,
    JevClient,
    JevValidationError,
    Noul,
    NoulAnswer,
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
    "extract_items",
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
ItemKind = Literal["user", "assistant", "tool", "event"]

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
    """

    id: str
    kind: ItemKind
    text: str
    tokens: int
    ts: str | None
    turn: int


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


def extract_items(transcript_path: str | Path) -> list[Item]:
    """Walk one transcript JSONL and return its extracted, chronologically ordered items.

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
       heartbeat-protocol reply (`transcript_roles.is_heartbeat_reply`). Real work a
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
                if _is_heartbeat_entry(entry):
                    continue  # the fire's OWN prompt -- always dropped, see point 2 above

                role = transcript_roles.classify_record(entry)
                if role == "skip":
                    continue  # sidechain (already caught above)/compact-summary/meta
                kind: ItemKind = "user" if role == "human" else "event"

                if isinstance(content, str):
                    items.append(Item(f"{uuid}:0", kind, content,
                                       estimate_tokens(content), ts, turn))
                    turn += 1
                elif isinstance(content, list):
                    for idx, block in enumerate(content):
                        if not isinstance(block, dict):
                            continue
                        btype = block.get("type")
                        if btype == "text":
                            text = block.get("text", "")
                            items.append(Item(f"{uuid}:{idx}", kind, text,
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
                            text = f"{name}({tool_input})\n{result_text}"
                            items.append(Item(f"{uuid}:{idx}", "tool", text,
                                               estimate_tokens(text), ts, turn))
                            turn += 1
                # else: no content (or an unrecognised shape) -- nothing to extract.

            elif entry_type == "attachment":
                # Defect 4 (orchestrator scope extension): a mid-turn queued record -- the
                # owner typed while a turn was running, or a task-notification was delivered
                # mid-turn. Every other attachment kind (hook output, ...) is noise.
                attachment = entry.get("attachment")
                if not isinstance(attachment, dict) or attachment.get("type") != "queued_command":
                    continue
                text = attachment.get("prompt", "")
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
    retry is); if the budget is spent, this re-raises the triggering error immediately,
    which `score_items`'s existing fail-closed handling turns into a whole-call failure --
    deliberate: a backend blocking/oversizing enough to exhaust the cap needs the caller
    to fall back, not to keep grinding through more splits.

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
        for half in (left, right):
            if not retry_budget.take():
                raise  # cap exhausted -- see docstring: bail the whole call, don't degrade
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
    that is still unscoreable once split all the way down becomes a pointer-only `Scores`
    entry (`kept=False, oversized=False` -- rendered by `compose()` exactly like any other
    below-threshold item, no inlined text: the verbatim guarantee holds because a
    never-scored item's text is never sent again, let alone altered) instead of failing the
    whole compaction -- UNLESS literally every batch ends up blocked, which raises
    `JevBlockedError` (nothing was actually compacted, so this must count as a Jev failure
    and let the caller fall back, not silently emit an all-pointers document as if it
    succeeded).
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

    if blocked_ids and not scores:
        # Every batch ended up blocked -- nothing was actually compacted (see docstring):
        # this is a Jev failure, not a (useless) all-pointers success.
        raise JevBlockedError(
            f"every batch was blocked or oversized ({len(blocked_ids)} item(s)); "
            "nothing could be scored"
        )
    for item_id in blocked_ids:
        # Never scored, never inlined -- see docstring's verbatim-guarantee note.
        scores[item_id] = Scores(relevance=0.0, decision=0.0, oversized=False, kept=False,
                                  decision_passed=False)
    return scores


def _format_pointer(item: Item) -> str:
    """The elided-item stand-in text, via `jevctx.pipeline.format_pointer` (card 5,
    TRDD-HWF3QFAB). The local literal this replaced had no escaping -- a `"` or `\\` in an
    item's first line produced a pointer `pipeline.parse_pointer`/`find_pointers` could not
    parse back -- and previewed the literal first line even when it was blank; the summary
    below is the first NON-EMPTY line instead, truncated the same way as before. `lines=None`:
    this project's pointer ids resolve straight into the transcript JSONL
    (`jev_compact.py::_extract_block`), never into a sub-span of one block, so the
    `lines=a-b` field `format_pointer` supports for segment-level pointers (card 6, not this
    one) never applies here. WHY no path either: a pointer must never hand the model
    something it could `Read` -- the transcript is 24-258 MB (docs_dev/jev-compaction-spec.md
    card 3) -- so the path lives once, in the header, never per pointer.
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
# relevance/decision signal at all; the extra 20 lines give the model enough to decide
# whether `expand` is worth it, which the 80-char preview alone cannot.
_OVERSIZED_PREVIEW_LINES = 20


def _oversized_preview(item: Item) -> str:
    return "\n".join(item.text.splitlines()[:_OVERSIZED_PREVIEW_LINES])



# Card 5 content-fit measured fact (reports/compaction-replacement/): the appended note for a
# digest truncated by compose()'s max_bytes backstop -- see compose()'s own docstring.
_DIGEST_TRUNCATED_NOTE = "\n\n[[digest truncated to fit the handoff budget]]"


# Card 5 measured fact (docs_dev/jev-compaction-spec.md card 5 / reports/compaction-replacement/
# 20260923_064108+0200-hook-output-experiments.md): the largest real transcript elides ~18,041
# items -- one pointer line per elided item made `compose()` itself emit ~2.4 MB, independent of
# `budget_tokens` (that budget only bounds KEPT items). Cap the pointer list so its size no longer
# scales with transcript size; the items dropped from the list are still `expand`-able by id, the
# model just is not told about them by name.
_MAX_ELIDED_POINTERS = 40


def compose(
    items: list[Item],
    scores: dict[str, Scores],
    *,
    budget_tokens: int = 8000,
    header: dict[str, Any],
    max_elided_pointers: int = _MAX_ELIDED_POINTERS,
    max_bytes: int | None = None,
    full_context_path: str | None = None,
) -> str:
    """Assemble the final injected document: header, kept items verbatim, then pointers.

    `header` carries: `transcript_path`, `session_key`, `digest`, and an optional `usage`
    dict (`{"tokens": int, "cost": float}` from the Jev response). The transcript path is
    written out exactly twice by design -- once in the header, once in the fixed trailing
    "expand with" line -- never inside an individual pointer.

    `full_context_path`, when given (card 5 two-renderings, TRDD-RAEGS1D5): this render is a
    CAPPED companion to a separate, uncapped `compose()` call over the SAME `items`/`scores`
    ("score once, render twice" -- the caller never re-scores). One extra line is appended,
    right before the fixed "pointers expand with" trailer: "Full compacted context: <path> --
    read it ONLY if what you need is not shown above; try `expand --list` first." (reworded in
    the card 5 injection-caps review, TRDD-RAEGS1D5 -- the old "Read it for everything not
    shown here" phrasing invited an ~11k-token read of the whole full document on every capped
    render) -- the capped rendering's own way back to everything the byte backstop below had to
    drop, once the cheap targeted `expand --list --grep` path genuinely is not enough.

    `max_bytes`, when given, is a BACKSTOP (card 5 content-fit, TRDD-RAEGS1D5): the caller is
    expected to size `budget_tokens` / the digest / `max_elided_pointers` so the document
    already fits in the common case (measured: reports/compaction-replacement/ -- the pointer
    list, not the kept-items budget, dominated the old default). This only degrades further
    when a PARTICULAR transcript still overflows -- e.g. an unusually verbose digest or long
    pointer previews -- and it degrades in priority order, never a blind byte slice: (1) drop
    kept items by the SAME `evict_key` priority the `budget_tokens` eviction above already
    uses -- lowest (decision_passed, max_score) first, oldest among ties -- never bare
    chronological order, so a decision-passed item (a user instruction/correction) is not
    sacrificed ahead of a newer, lower-priority one just for being older, (2) drop pointers
    LOWEST-SCORE-first (the ones already least likely to be worth expanding), (3) truncate the
    digest text itself. The trailing "pointers
    expand with:" line is NEVER dropped by any of this -- it is the model's only way back to
    everything elided, and a blind `raw[:room]` slice downstream (`external_clear.compose_
    handoff`, before this fix) used to cut it off along with the newest kept items because both
    sit at the tail of the joined string.
    """
    # Oversized is re-checked here, not just trusted from `scores[...].kept`, because
    # "never inlined" is the compose-time invariant the spec actually cares about -- this
    # function is where inlining happens, so this is where the guard has to hold even if a
    # caller builds `scores` by hand (as the tests do) instead of via `score_items`.
    kept_items = [
        it for it in items if scores[it.id].kept and not scores[it.id].oversized
    ]

    def max_score(it: Item) -> float:
        s = scores[it.id]
        return max(s.relevance, s.decision)

    def evict_key(it: Item) -> tuple[bool, float, int]:
        # (decision_passed, max_score, turn) ascending: a relevance-only item (`False`)
        # sorts, and is dropped, BEFORE any item that passed the decision question -- "never
        # let the budget undo the decision question" (a user-stated decision, constraint,
        # correction or instruction the user gave later work must obey is worse to lose than
        # merely-relevant background). Within each group, lowest score first, oldest
        # (smallest `turn`) among equal scores -- unchanged from before.
        return (scores[it.id].decision_passed, max_score(it), it.turn)

    total_tokens = sum(it.tokens for it in kept_items)
    kept_ids = {it.id for it in kept_items}
    if total_tokens > budget_tokens:
        for it in sorted(kept_items, key=evict_key):
            if total_tokens <= budget_tokens:
                break
            kept_ids.discard(it.id)
            total_tokens -= it.tokens

    # `items` is already chronological, so filtering it (rather than re-sorting) keeps the
    # elided list chronological for free -- `max_elided_pointers` below only needs to pick
    # WHICH ids survive, not reorder anything.
    elided_items = [it for it in items if it.id not in kept_ids]
    hidden_count = 0
    if len(elided_items) > max_elided_pointers:
        # Highest max(relevance, decision) first -- the items most worth a pointer are the
        # ones the model was closest to keeping, not an arbitrary chronological head/tail.
        top_ids = {
            it.id
            for it in sorted(elided_items, key=max_score, reverse=True)[:max_elided_pointers]
        }
        shown_elided = [it for it in elided_items if it.id in top_ids]
        hidden_count = len(elided_items) - len(shown_elided)
    else:
        shown_elided = elided_items

    transcript_path = header.get("transcript_path", "")
    usage = header.get("usage") or {}

    def render(kept: set[str], elided: list[Item], hidden: int, digest_text: str) -> str:
        lines: list[str] = [
            "# Compacted context (Jev compaction)",
            f"transcript: {transcript_path}",
            f"session: {header.get('session_key', '')}",
            "",
            "## Digest",
            digest_text,
            "",
            f"usage: tokens={usage.get('tokens', '?')} cost={usage.get('cost', '?')}",
            "",
            "## Kept items",
        ]
        for it in items:  # `items` is already chronological -- preserve it verbatim
            if it.id in kept:
                lines.append(f"-- {it.kind} {it.id} --")
                lines.append(it.text)

        lines.append("")
        lines.append("## Elided")
        elided_ids = {it.id for it in elided}
        for it in items:
            if it.id in elided_ids:
                lines.append(_format_pointer(it))
                if scores[it.id].oversized:
                    lines.append(_oversized_preview(it))
        if hidden:
            # Card 5 content-fit (TRDD-RAEGS1D5, item 3): a bare "N more items not listed" was
            # a dead end -- `expand` needs an id, and an id not shown here could never be
            # named. `expand --list [--grep TEXT]` (added alongside this line) walks the SAME
            # transcript and prints every item's id, so this points the model at that instead
            # of leaving it to guess or give up.
            lines.append(
                f"[[elided: {hidden} more items not listed -- list/search them with: uv run "
                '--script "$CLAUDE_PLUGIN_ROOT/scripts/jev_compact.py" expand --transcript '
                f'{transcript_path} --list --grep TEXT]]'
            )

        if full_context_path:
            # Card 5 two-renderings (TRDD-RAEGS1D5): the capped rendering's own way back to the
            # uncapped document composed from the SAME items/scores -- see the docstring. Card
            # 5 injection-caps review (TRDD-RAEGS1D5): "Read it for everything not shown here"
            # invited an ~11k-token read of the whole full document on every capped render --
            # reworded to try `expand --list` first, the cheap targeted path, and read the full
            # document only when that genuinely is not enough.
            lines.append("")
            lines.append(
                f"Full compacted context: {full_context_path} -- read it ONLY if what you "
                "need is not shown above; try list/search first: uv run --script "
                '"$CLAUDE_PLUGIN_ROOT/scripts/jev_compact.py" expand --transcript '
                f"{transcript_path} --list --grep TEXT."
            )

        lines.append("")
        lines.append(
            'pointers expand with: uv run --script "$CLAUDE_PLUGIN_ROOT/scripts/jev_compact.py" '
            f"expand --transcript {transcript_path} <id>"
        )
        return "\n".join(lines)

    digest_text = header.get("digest", "")
    doc = render(kept_ids, shown_elided, hidden_count, digest_text)
    if max_bytes is None or len(doc.encode("utf-8")) <= max_bytes:
        return doc

    # Backstop degrade, in priority order -- see the docstring. Each step only runs if the
    # previous one was not enough; `kept_order`/`ranked` are popped from one end so this is
    # bounded (at most `len(items)` iterations total) and never loops forever.
    #
    # `kept_order` is sorted by `evict_key` -- the SAME (decision_passed, max_score, turn)
    # priority the budget_tokens eviction above already uses -- not by bare chronological
    # position (review finding, card 5 content-fit): a plain "oldest first" pop would drop a
    # decision-passed item (a user instruction/correction the budget eviction deliberately
    # protects) ahead of a newer, lower-priority relevance-only item just because it happens
    # to be older, reintroducing at this second checkpoint exactly the loss `evict_key` exists
    # to prevent at the first one. Oldest-among-equal-priority is still the tiebreaker
    # (`evict_key`'s third field), matching the "oldest kept items first" instruction wherever
    # priority does not already decide it.
    kept_order = sorted((it for it in items if it.id in kept_ids), key=evict_key)
    while kept_order and len(doc.encode("utf-8")) > max_bytes:
        kept_ids.discard(kept_order.pop(0).id)
        doc = render(kept_ids, shown_elided, hidden_count, digest_text)

    if len(doc.encode("utf-8")) > max_bytes and shown_elided:
        ranked = sorted(shown_elided, key=max_score)  # lowest score first == first to drop
        while ranked and len(doc.encode("utf-8")) > max_bytes:
            dropped = ranked.pop(0)
            shown_elided = [it for it in shown_elided if it.id != dropped.id]
            hidden_count += 1
            doc = render(kept_ids, shown_elided, hidden_count, digest_text)

    if len(doc.encode("utf-8")) > max_bytes and digest_text:
        overflow = len(doc.encode("utf-8")) - max_bytes
        digest_bytes = digest_text.encode("utf-8")
        note_bytes = len(_DIGEST_TRUNCATED_NOTE.encode("utf-8"))
        keep = max(0, len(digest_bytes) - overflow - note_bytes)
        digest_text = digest_bytes[:keep].decode("utf-8", "ignore").rstrip() + _DIGEST_TRUNCATED_NOTE
        doc = render(kept_ids, shown_elided, hidden_count, digest_text)

    return doc
