"""Classifies one Claude Code transcript JSONL entry by who/what actually authored it.

TRDD-RAEGS1D5 (2026-09-23), orchestrator scope extension following an adversarial review of
commit 2353a88a: that commit's `jev_compaction.is_human_record` only ever answers a two-way
question ("human or not") -- but Claude Code writes at least six OTHER classes of `type:
"user"` (and, since the mid-turn-queue mechanism, `type: "attachment"`) record: task
notifications, heartbeat prompts, local-command wrappers, interrupt markers, peer/coordinator
messages, and harness compact summaries. A two-way test cannot tell these apart, so a
task-notification or a compact summary kept being scored/digested as if the human had typed
it. This module is the ONE shared, stdlib-only classifier -- built only from field values
measured on real transcripts (reports/compaction-replacement/
20260923_200805+0200-jev-reference-gap-analysis.md §2.1) -- every extraction/injection call
site must use, so the SAME entry is never classified two different ways in two different
files (`jev_compaction.py` today; `external_clear.recent_messages` and
`pre-compact-handoff._recent_turns` on a later card per the gap analysis §4).
"""

from __future__ import annotations

from typing import Any, Literal

__all__ = [
    "RecordRole",
    "HEARTBEAT_PREFIX",
    "classify_record",
    "is_heartbeat_reply",
]

RecordRole = Literal["skip", "human", "notification", "system", "peer"]

#: The janitor heartbeat fire's own fixed prompt prefix (`janitor-heartbeat-protocol.md`).
#: Public (unlike the other prefixes below) because `jev_compaction.extract_items` also needs
#: it directly, to always skip the fire's OWN initiating prompt outright -- a stronger drop
#: than the "system" role's usual "kept, tagged" handling (see that module's `_is_heartbeat_entry`).
HEARTBEAT_PREFIX = "[janitor-heartbeat]"

_NOTIFICATION_PREFIX = "<task-notification>"
# Order doesn't matter for `str.startswith` with a tuple -- first structural match wins,
# unlike `classify_record`'s own rule ordering below.
_SYSTEM_PREFIXES = (
    "<local-command-stdout>",
    "<local-command-caveat>",
    "<command-message>",
    HEARTBEAT_PREFIX,
    "[Request interrupted",
)
_COMMAND_NAME_PREFIX = "<command-name>"

_HEARTBEAT_REPLY_TEXT = "janitor heartbeat"
# Report §4 glue item 1's own definition ("only the protocol reply"): the janitor-heartbeat-
# protocol rule's own quiet contract prints "janitor heartbeat" then at most 2 drift lines, so
# a bare reply is at most 3 lines -- a 4th line means real content rode along and the whole
# text must be kept.
_HEARTBEAT_REPLY_MAX_LINES = 3


def _primary_text(entry: dict[str, Any]) -> str:
    """The one text string a `type: "user"`/`"assistant"` entry is classified by.

    The plain string `message.content`, or the first `text`-type block's text when content is
    a list of blocks. An entry with no text at all (e.g. a `tool_result`-only record) yields
    `""` -- deliberately: it must never spuriously match a fixed prefix below.
    """
    content = entry.get("message", {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                return block.get("text", "")
    return ""


def classify_record(entry: dict[str, Any]) -> RecordRole:
    """Classify one transcript JSONL entry. First matching rule wins.

    Ordered exactly per the gap analysis §4 glue item 1 -- built only from field values
    measured on real transcripts (§2.1), nothing guessed:

    1. `isSidechain` -> "skip" (a subagent's own turn, not the main conversation).
    2. `isCompactSummary` / `isVisibleInTranscriptOnly` -> "skip" (harness-generated prose,
       "This session is being continued...").
    3. `isMeta` -> "skip" (hook-injected hidden context).
    4. A fixed TEXT prefix, checked BEFORE `turnOrigin` -- a `<local-command-stdout>` record
       can itself carry `turnOrigin: "human"` (the field marks the TURN, not this record's own
       author), so the record's own wrapper tag must win first: `<task-notification>` ->
       "notification"; `<local-command-stdout>`, `<local-command-caveat>`,
       `<command-message>`, `[janitor-heartbeat]` or `[Request interrupted` -> "system".
    5. `origin.kind` (Claude Code's own newer, most specific signal, so it outranks
       `turnOrigin`/`promptSource` below): `human` -> "human"; `task-notification` ->
       "notification"; `peer`/`coordinator` -> "peer"; `auto-continuation` -> "system";
       anything else (including the measured value `"unclassified"`) falls through.
    6. `turnOrigin`: `human` -> "human"; `scheduled` -> "system"; `task_notification` ->
       "notification"; `peer` -> "peer"; `sdk` -> "human" (an operator's input to a headless
       session is still a human's words -- owner-level decision, orchestrator 2026-09-23).
    7. `promptSource`: `typed`/`queued` -> "human"; `system` -> "system"; `sdk` -> "human".
    8. Text starts with `<command-name>` -> "human" (a typed slash command; its args are
       human text).
    9. No field above matched at all (a legacy, pre-`origin` transcript record) -> "human".

    Tool-result blocks are NOT classified by this function -- `jev_compaction.extract_items`
    keeps its own pairing-based handling for those regardless of the entry's role (report §4
    glue item 1: "Tool-result blocks keep today's handling, whatever the record's origin").
    """
    if entry.get("isSidechain"):
        return "skip"
    if entry.get("isCompactSummary") or entry.get("isVisibleInTranscriptOnly"):
        return "skip"
    if entry.get("isMeta"):
        return "skip"

    text = _primary_text(entry)
    if text.startswith(_NOTIFICATION_PREFIX):
        return "notification"
    if text.startswith(_SYSTEM_PREFIXES):
        return "system"

    origin = entry.get("origin")
    if isinstance(origin, dict):
        kind = origin.get("kind")
        if kind == "human":
            return "human"
        if kind == "task-notification":
            return "notification"
        if kind in ("peer", "coordinator"):
            return "peer"
        if kind == "auto-continuation":
            return "system"
        # any other value (measured: "unclassified") falls through to turnOrigin below.

    turn_origin = entry.get("turnOrigin")
    if turn_origin == "human":
        return "human"
    if turn_origin == "scheduled":
        return "system"
    if turn_origin == "task_notification":
        return "notification"
    if turn_origin == "peer":
        return "peer"
    if turn_origin == "sdk":
        return "human"

    prompt_source = entry.get("promptSource")
    if prompt_source in ("typed", "queued"):
        return "human"
    if prompt_source == "system":
        return "system"
    if prompt_source == "sdk":
        return "human"

    if text.startswith(_COMMAND_NAME_PREFIX):
        return "human"

    return "human"  # legacy record: no origin/turnOrigin/promptSource field at all


def is_heartbeat_reply(text: str) -> bool:
    """True iff `text` is ONLY the janitor heartbeat protocol's bare quiet reply.

    Used to drop an assistant text block that is pure heartbeat-protocol noise while keeping
    everything else a heartbeat-triggered turn did (TRDD-RAEGS1D5 defect 1: the ORIGINAL
    fix over-dropped a whole turn's worth of real work -- reads, edits, dispatches -- because
    it skipped everything between a heartbeat prompt and the next human record). Matches the
    janitor-heartbeat-protocol rule's own quiet contract: "reply with exactly `janitor
    heartbeat`" or, when a drift line rides along, "`janitor heartbeat` then those lines
    verbatim, adding at most 2 lines" -- so a match requires BOTH the exact leading phrase and
    a total of 3 lines or fewer; a real report that merely starts with the same words but runs
    longer must never be dropped.
    """
    stripped = text.strip()
    if not stripped.startswith(_HEARTBEAT_REPLY_TEXT):
        return False
    return len(stripped.splitlines()) <= _HEARTBEAT_REPLY_MAX_LINES
