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

import re
import sys
from typing import Any, Literal

__all__ = [
    "RecordRole",
    "HEARTBEAT_PREFIX",
    "classify_record",
    "is_heartbeat_reply",
    "is_control_input",
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
_COMMAND_NAME_RE = re.compile(r"<command-name>(.*?)</command-name>", re.S)

#: TRDD-RAEGS1D5, coordinator correction (2): the janitor itself TYPES these into the pane
#: with real keystrokes -- Claude Code records that identically to an owner-typed command
#: (same `<command-message>`/`<command-name>` shape, same `origin.kind: "human"`/absent), so
#: without this list they'd count as "human" and fill an unattended session's digest "last
#: three human messages" with the janitor's own automation. Exact bare names (no plugin
#: qualifier possible for these three).
_AUTOMATION_COMMAND_NAMES_EXACT = ("clear", "compact", "reload-plugins")
#: Prefix match for the `/janitor-*` family and its plugin-qualified `/ai-maestro-janitor:*`
#: form (resume, arm, and so on) -- both forms are checked with the leading "/" stripped.
_AUTOMATION_COMMAND_NAME_PREFIXES = ("janitor-", "ai-maestro-janitor:")


def _is_automation_command_name(name: str) -> bool:
    """True iff `name` (a `<command-name>` tag's text) is one of the janitor's own typed
    commands, bare or plugin-qualified, with or without a leading slash."""
    normalized = name.strip()
    if normalized.startswith("/"):
        normalized = normalized[1:]
    if normalized in _AUTOMATION_COMMAND_NAMES_EXACT:
        return True
    return normalized.startswith(_AUTOMATION_COMMAND_NAME_PREFIXES)



#: TRDD-DZ1KOGAC, gap found on real transcripts: a slash command usually arrives wrapped in
#: Claude Code's own generated boilerplate, e.g.
#: `<command-message>usage-credits</command-message>\n<command-name>/usage-credits</command-name>\n
#: <command-args></command-args>` -- and an EMPTY `<command-args>` wrapper is AS content-free
#: as a bare `/usage-credits` -- but ONLY for a command whose NAME itself carries no decision.
#: Orchestrator correction after review: unlike the bare-slash-command branch, an empty wrapper
#: must NOT be content-free for every command -- `/janitor-disarm`, `/janitor-global-disarm`,
#: `/janitor-auto-manage-oauth-off`, `/ponytail`, `/colony` and the like are themselves the
#: owner's decision (the command name IS the content), so only this small, explicit set of
#: read-only/no-op-ish commands may be treated as content-free when their args are empty.
#: `re.S` because `<command-message>` text can span lines.
_COMMAND_MESSAGE_TAG_RE = re.compile(r"<command-message>.*?</command-message>", re.S)
_COMMAND_NAME_TAG_RE = re.compile(r"<command-name>(.*?)</command-name>", re.S)
_COMMAND_ARGS_TAG_RE = re.compile(r"<command-args>(.*?)</command-args>", re.S)
_CONTENT_FREE_WRAPPER_COMMAND_NAMES = frozenset(
    {
        "compact",
        "clear",
        "usage-credits",
        "usage",
        "cost",
        "context",
        "status",
        "help",
        "reload-plugins",
        "doctor",
    }
)


def _is_content_free_wrapper_command_name(name: str) -> bool:
    """True iff `name` (a `<command-name>` tag's text) is a command whose empty-args
    invocation is content-free -- deliberately NOT the `_is_automation_command_name`
    `janitor-*`/`ai-maestro-janitor:*` prefix match, since those names (e.g.
    `/janitor-disarm`) are themselves owner decisions, not no-ops."""
    normalized = name.strip()
    if normalized.startswith("/"):
        normalized = normalized[1:]
    return normalized in _CONTENT_FREE_WRAPPER_COMMAND_NAMES


def _is_empty_command_wrapper(stripped: str) -> bool:
    """True iff `stripped` is ONLY a `<command-message>`/`<command-name>`/`<command-args>`
    wrapper, any order, with `<command-args>` absent or empty/whitespace-only, and
    `<command-name>` is one `_is_content_free_wrapper_command_name` allows.

    Removes each tag (found anywhere in what is left, so order doesn't matter) and requires
    nothing but whitespace to remain -- a wrapper missing `<command-message>` or
    `<command-name>`, a non-content-free command name, one with a non-empty `<command-args>`,
    or one followed by real owner text all fail this and fall through to `is_control_input`'s
    ordinary branches.
    """
    remainder = stripped
    message_match = _COMMAND_MESSAGE_TAG_RE.search(remainder)
    if message_match is None:
        return False
    remainder = remainder[: message_match.start()] + remainder[message_match.end() :]
    name_match = _COMMAND_NAME_TAG_RE.search(remainder)
    if name_match is None:
        return False
    if not _is_content_free_wrapper_command_name(name_match.group(1)):
        return False
    remainder = remainder[: name_match.start()] + remainder[name_match.end() :]
    args_match = _COMMAND_ARGS_TAG_RE.search(remainder)
    if args_match is not None:
        if args_match.group(1).strip():
            return False
        remainder = remainder[: args_match.start()] + remainder[args_match.end() :]
    return remainder.strip() == ""


#: TRDD-DZ1KOGAC: an owner-typed bare control word carries `origin.kind: "human"`/absent, same
#: as any real instruction, so `classify_record` correctly calls it "human" -- authorship is
#: true. But it has no content: measured on real transcripts, a bare "resume"/"continue" or an
#: unwrapped, argument-less `/compact`/`/clear` (no `<command-message>` wrapper at all, so
#: `_is_automation_command_name` above never even sees it) was displacing the owner's real
#: instructions out of the injected copy's owner tier, the guaranteed newest-owner slot, and
#: the digest -- it scored like a decision because Jev has no other signal, then every other
#: item got compared against "resume". The fix is content-based, not authorship-based: keep the
#: role "human" (it IS the owner's own words) and let callers demote only the ITEM KIND.
_CONTROL_TOKENS = frozenset({"resume", "continue"})
_BARE_SLASH_COMMAND_RE = re.compile(r"^/(\S+)$")


def is_control_input(text: str) -> bool:
    """True iff `text`, stripped, is nothing but a bare control word (optionally followed only
    by trailing punctuation from `.!`, e.g. "resume." or "Continue!"), an argument-less
    automation slash command, or an empty-args `<command-message>`/`<command-name>`/
    `<command-args>` wrapper -- content-free regardless of who typed it.

    Matches: a single token `resume`/`continue` (case-insensitive), with or without trailing
    `.`/`!`; `/name` with no arguments where `name` is one `_is_automation_command_name`
    already treats as automation (reusing that list rather than duplicating it); or a
    `<command-message>`/`<command-name>`/`<command-args>` wrapper, in any order, whose
    `<command-args>` is absent or empty/whitespace-only AND whose `<command-name>` is one of
    the small, explicit read-only/no-op set `_is_content_free_wrapper_command_name` allows
    (TRDD-DZ1KOGAC coordinator correction: measured a real transcript where an empty-args
    `/usage-credits` wrapper took the guaranteed newest-owner slot). Does NOT match a slash
    command WITH arguments (`/goal evaluate the plugin`), an empty-args wrapper whose command
    name is itself an owner decision (`/janitor-disarm`, `/janitor-global-disarm`,
    `/janitor-auto-manage-oauth-off`, `/ponytail`, `/colony`) -- the name IS the content there,
    unlike a bare `/compact` -- a wrapper whose `<command-args>` carries text (`/eli5 the
    decision i have to make`), a wrapper followed by extra owner text, a trailing `?`
    (`resume?` is the owner asking a question, not a content-free control word), or a real
    reply that merely contains one of these words (`resume the pending TRDD work`, `ok go on`,
    `yes, post it`) -- those are the owner's actual words and must keep their standing.
    """
    stripped = text.strip()
    bare = stripped.rstrip(".!")
    if bare.lower() in _CONTROL_TOKENS:
        return True
    if _is_empty_command_wrapper(stripped):
        return True
    match = _BARE_SLASH_COMMAND_RE.match(stripped)
    if match is None:
        return False
    return _is_automation_command_name(match.group(1))

#: TRDD-RAEGS1D5, coordinator correction: measured 7,190 records with `origin.kind ==
#: "unclassified"` -- mostly list/tool_result carriers, not an oddity. It means "origin gives
#: no decision", not "an unrecognised kind"; it must fall through to `turnOrigin` exactly like
#: a missing `kind`, never be treated as defect 2's unknown-value case (that would misfile any
#: list-content human message carrying it, and flood stderr on every one of the 7,190).
_ORIGIN_KIND_NO_DECISION = "unclassified"

#: Which unrecognised `origin.kind` values have already been named on stderr THIS process
#: (coordinator correction: at most once per distinct value, not once per record -- printing
#: unconditionally would flood stderr in jev_compaction.py and the hooks on any bulk transcript
#: scan). Module-level by design: the whole point is a process-wide dedupe, not a per-call one.
# ponytail: unbounded, never evicted -- assumes origin.kind is a small, harness-controlled
# enum (adversarial review confirmed: only a handful of distinct values observed in practice),
# so the set stays tiny for the life of the process. If a future record source ever feeds this
# classifier attacker-controlled or high-cardinality kind strings, add an LRU/max-size bound.
_warned_unknown_origin_kinds: set[str] = set()

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
       "notification"; a typed-command wrapper PAIR -- BOTH `<command-message>` AND
       `<command-name>` present, text starting with EITHER one (the two tags are also observed
       in that reversed, name-first order on real transcripts -- gap fix below) -- with
       `origin.kind` "human" or absent -> "human" (TRDD-RAEGS1D5
       defect 1: measured on real transcripts, every such wrapper record has `origin.kind:
       "human"` or no `origin` field at all -- the generic wrapper-prefix rule below was
       matching it first and dropping owner instructions like `/task ...`/`/loop 5m ...` as
       "system"), EXCEPT a `<command-name>` naming the janitor's own typed automation
       (`/clear`, `/compact`, `/reload-plugins`, `/janitor-*`, `/ai-maestro-janitor:*`, bare or
       plugin-qualified, with or without the leading slash) -> "system" ALWAYS, even with a
       non-empty `<command-args>` (coordinator correction 4, superseding an earlier
       args-presence tie-breaker: the janitor itself types `/reload-plugins --force` and
       `/janitor-compact-context --hard` -- args riding along does not make it the owner's
       words. The args exception applies only to NON-automation commands, which fall to
       "human" regardless of args -- command name alone decides for automation); otherwise
       `<local-command-stdout>`, `<local-command-caveat>`, `<command-message>`,
       `[janitor-heartbeat]` or `[Request interrupted` -> "system". Gap fix (orchestrator,
       2026-09-25): a real transcript also carries `<command-name>` FIRST,
       `<command-message>` second (reports/compaction-replacement/
       20260925_025424+0200-trdd-dqxmnd59-v3-gaps-closed.md lines 110-118) -- that order used
       to skip this rule entirely (only `<command-message>`-first was checked) and reach the
       generic `_SYSTEM_PREFIXES`/legacy-fallback path, which decides by tag presence alone
       and never checks automation, so a reversed-order `/reload-plugins` was misclassified
       "human" instead of "system". The decision is now order-independent: the wrapper PAIR
       (both tags present) decides, and only the tags' order is irrelevant -- a bare
       `<command-name>` with no `<command-message>` companion at all does NOT match this rule
       (falls through to rule 8 below), since that is a different, unmeasured shape the
       reported gap never described.
    5. `origin.kind` (Claude Code's own newer, most specific signal, so it outranks
       `turnOrigin`/`promptSource` below): `human` -> "human"; `task-notification` ->
       "notification"; `peer`/`coordinator` -> "peer"; `auto-continuation` -> "system"; any
       OTHER non-empty value EXCEPT `"unclassified"` (TRDD-RAEGS1D5 defect 2 -- an explicit
       kind this classifier doesn't recognise) -> "notification" (stderr-named once per
       distinct value per process), never a fall-through to `turnOrigin` below (that chain
       treats "no known signal" as human, so a future system-authored kind would silently
       count as the owner's own words); `"unclassified"` itself (coordinator correction: a
       real, frequent value -- 7,190 records measured, mostly list/tool_result carriers --
       meaning "origin gives no decision", not an unrecognised kind) or a missing `kind` key
       both fall through to `turnOrigin`, same as no `origin` field at all.
    6. `turnOrigin`: `human` -> "human"; `scheduled` -> "system"; `task_notification` ->
       "notification"; `peer` -> "peer"; `sdk` -> "human" (an operator's input to a headless
       session is still a human's words -- owner-level decision, orchestrator 2026-09-23).
    7. `promptSource`: `typed`/`queued` -> "human"; `system` -> "system"; `sdk` -> "human".
    8. No field above matched at all (a legacy, pre-`origin` transcript record, or any other
       unhandled shape) -> "human". A dedicated `<command-name>`-prefix check used to sit here
       too, but it always returned the same "human" this catch-all already returns -- dead code,
       removed (TRDD-RAEGS1D5 gap-fix review).

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
    origin = entry.get("origin")
    origin_kind = origin.get("kind") if isinstance(origin, dict) else None

    if text.startswith(_NOTIFICATION_PREFIX):
        return "notification"
    # Defect 1 (TRDD-RAEGS1D5, review): a typed slash command's wrapper carries a
    # `<command-name>` tag (measured on real transcripts -- see the docstring), and its
    # origin.kind is "human" or absent. The generic `_SYSTEM_PREFIXES` check below matches a
    # leading `<command-message>` regardless of who sent it, so this must be decided first or
    # every `/task ...`/`/loop ...` the owner typed is dropped as "system".
    #
    # TRDD-RAEGS1D5 gap fix: the two wrapper tags are NOT always in `<command-message>` /
    # `<command-name>` order -- a real transcript also carries the reversed order
    # (`<command-name>` first, `<command-message>` second; see reports/compaction-replacement/
    # 20260925_025424+0200-trdd-dqxmnd59-v3-gaps-closed.md lines 110-118). Requiring the text to
    # START WITH `<command-message>` specifically skipped that shape and let it fall through to
    # the `_COMMAND_NAME_PREFIX` fallback below, which decides purely by presence (never checks
    # automation), so `/reload-plugins` in reversed order was misclassified "human". The decision
    # must be the same regardless of which wrapper tag comes first -- but ONLY for the actual
    # two-tag wrapper PAIR (`<command-message>` AND `<command-name>` BOTH present): the review
    # for this fix flagged that matching on `<command-name>` presence alone would also catch a
    # bare `<command-name>...</command-name>` fragment with no `<command-message>` companion at
    # all -- an unmeasured, different shape the reported gap never described -- so both tags are
    # required, only their ORDER is irrelevant.
    if (
        (text.startswith("<command-message>") or text.startswith(_COMMAND_NAME_PREFIX))
        and "<command-message>" in text
        and _COMMAND_NAME_PREFIX in text
        and origin_kind in (None, "human")
    ):
        name_match = _COMMAND_NAME_RE.search(text)
        command_name = name_match.group(1).strip() if name_match else ""
        if _is_automation_command_name(command_name):
            # Coordinator correction (4, superseding correction 2's args tie-breaker): the
            # janitor's own typed automation is ALWAYS "system", even with non-empty args --
            # it types `/reload-plugins --force` and `/janitor-compact-context --hard` itself,
            # so an args-presence check would have wrongly promoted those back to "human". The
            # args exception applies ONLY to non-automation commands (`/task ...`,
            # `/loop 5m <prompt>`), which fall through to "human" below regardless of args --
            # command NAME alone decides for automation, never args.
            return "system"
        return "human"
    if text.startswith(_SYSTEM_PREFIXES):
        return "system"

    if isinstance(origin, dict):
        kind = origin_kind
        if kind == "human":
            return "human"
        if kind == "task-notification":
            return "notification"
        if kind in ("peer", "coordinator"):
            return "peer"
        if kind == "auto-continuation":
            return "system"
        if kind is not None and kind != _ORIGIN_KIND_NO_DECISION:
            # Defect 2 (TRDD-RAEGS1D5, review): an unrecognised origin.kind must never
            # silently fall through to turnOrigin/promptSource/legacy -- that chain's final
            # fallback is "human", so a future system-authored kind would count as the
            # owner's own words. Route it to "notification" and name it on stderr, ONCE per
            # distinct value per process (coordinator correction: printing unconditionally
            # floods stderr on any bulk scan), so a new kind is visible instead of silent.
            if kind not in _warned_unknown_origin_kinds:
                _warned_unknown_origin_kinds.add(kind)
                print(f"transcript_roles: unknown origin.kind={kind!r}", file=sys.stderr)
            return "notification"
        # kind is None (origin dict present, no "kind" field) or "unclassified" (coordinator
        # correction: a real, frequent, deliberately-non-deciding value) -- falls through to
        # turnOrigin exactly like a missing kind.

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

    # No field above matched at all (a legacy, pre-`origin` transcript record, or a
    # `<command-name>`-leading wrapper whose origin.kind fell through as neither "human" nor
    # None) -- either way the outcome is "human", so a dedicated `_COMMAND_NAME_PREFIX` check
    # here would be dead code: it can only ever produce the same "human" this catch-all already
    # returns. Removed rather than kept as a no-op (TRDD-RAEGS1D5 gap-fix review).
    return "human"


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
