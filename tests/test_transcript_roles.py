"""Tests for scripts/lib/transcript_roles.py (TRDD-RAEGS1D5, orchestrator scope extension).

One test per measured record class from reports/compaction-replacement/
20260923_200805+0200-jev-reference-gap-analysis.md §2.1 -- each entry below mirrors the exact
field combination that table measured on real transcripts, not a guessed shape.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import transcript_roles as tr  # noqa: E402

# --- classify_record: one test per measured class, in the report's own rule order ---


def test_sidechain_is_skipped_regardless_of_everything_else() -> None:
    # Rule 1 -- a subagent's own turn; even a plainly-human-shaped body must still skip.
    entry = {"isSidechain": True, "origin": {"kind": "human"}, "message": {"content": "hi"}}
    assert tr.classify_record(entry) == "skip"


def test_compact_summary_is_skipped() -> None:
    # Rule 2 -- the harness's own "This session is being continued..." injection.
    entry = {
        "isCompactSummary": True, "isVisibleInTranscriptOnly": True,
        "message": {"content": "This session is being continued from a previous conversation."},
    }
    assert tr.classify_record(entry) == "skip"


def test_heartbeat_prompt_is_skipped_via_ismeta_not_via_system_role() -> None:
    # Measured shape: promptSource "system", isMeta TRUE, turnOrigin "scheduled" (newer),
    # text "[janitor-heartbeat]". Rule 3 (isMeta) fires before rule 4's text-prefix check, so
    # this returns "skip" here -- `jev_compaction._is_heartbeat_entry` intercepts the SAME
    # entry even earlier (by prefix alone) so extract_items never even calls classify_record
    # on it; this test only pins classify_record's own, narrower behaviour in isolation.
    entry = {
        "isMeta": True, "promptSource": "system", "turnOrigin": "scheduled",
        "message": {"content": "[janitor-heartbeat]\n/path/to/dispatcher-stub.py\n..."},
    }
    assert tr.classify_record(entry) == "skip"


def test_task_notification_is_role_notification() -> None:
    # Measured shape: origin.kind "task-notification", promptSource "system",
    # turnOrigin "task_notification" (newer), isMeta FALSE, text "<task-notification>".
    entry = {
        "isMeta": False, "origin": {"kind": "task-notification"}, "promptSource": "system",
        "turnOrigin": "task_notification",
        "message": {"content": "<task-notification>\n<status>completed</status>\n...</task-notification>"},
    }
    assert tr.classify_record(entry) == "notification"


def test_human_typed_with_origin_is_role_human() -> None:
    # Measured shape: origin.kind "human", promptSource "typed"|"queued", turnOrigin "human".
    entry = {
        "origin": {"kind": "human"}, "promptSource": "typed", "turnOrigin": "human",
        "message": {"content": "fix the deploy script"},
    }
    assert tr.classify_record(entry) == "human"


def test_local_command_stdout_is_system_even_with_turn_origin_human() -> None:
    # Rule 4 runs BEFORE rule 6 (turnOrigin) deliberately: a `<local-command-stdout>` record
    # can itself carry `turnOrigin: "human"` -- that field marks the TURN, not this record's
    # own author (report §4 glue item 1, point 4's own stated reason).
    entry = {
        "turnOrigin": "human",
        "message": {"content": "<local-command-stdout>\nsome command output\n</local-command-stdout>"},
    }
    assert tr.classify_record(entry) == "system"


def test_command_message_wrapper_is_system() -> None:
    entry = {"message": {"content": "<command-message>some-command</command-message>"}}
    assert tr.classify_record(entry) == "system"


def test_interrupt_marker_is_system() -> None:
    entry = {"message": {"content": [{"type": "text", "text": "[Request interrupted by user]"}]}}
    assert tr.classify_record(entry) == "system"


def test_command_name_wrapper_is_human() -> None:
    # Rule 8: `<command-name>` is a typed slash command -- a human invoked it, keep it "human".
    # No origin/turnOrigin/promptSource on this entry, so only rule 8 can classify it.
    entry = {"message": {"content": "<command-name>compact</command-name>"}}
    assert tr.classify_record(entry) == "human"


def test_peer_and_coordinator_origin_are_role_peer() -> None:
    # Measured: origin.kind "peer"/"coordinator" (mostly isMeta -- an explicit isMeta:False
    # entry is needed to reach rule 5 rather than being caught by rule 3 first).
    peer = {"isMeta": False, "origin": {"kind": "peer"}, "message": {"content": "status?"}}
    coordinator = {"isMeta": False, "origin": {"kind": "coordinator"}, "message": {"content": "go"}}
    assert tr.classify_record(peer) == "peer"
    assert tr.classify_record(coordinator) == "peer"


def test_auto_continuation_origin_is_system() -> None:
    entry = {"isMeta": False, "origin": {"kind": "auto-continuation"}, "message": {"content": "..."}}
    assert tr.classify_record(entry) == "system"


def test_unclassified_origin_falls_through_to_turn_origin() -> None:
    # Measured value "unclassified" (mostly on list/tool records) must fall through rule 5
    # rather than being treated as an unrecognised-but-terminal value.
    entry = {
        "isMeta": False, "origin": {"kind": "unclassified"}, "turnOrigin": "human",
        "message": {"content": "hi"},
    }
    assert tr.classify_record(entry) == "human"


def test_turn_origin_scheduled_without_origin_is_system() -> None:
    # A CronCreate/`/loop` job's own turn marker, no `origin` field at all (measured: a real
    # heartbeat entry carries this shape too, but that one is intercepted upstream by its own
    # prefix -- see jev_compaction.py's TRDD-RAEGS1D5 defect 2).
    entry = {"turnOrigin": "scheduled", "message": {"content": "run the nightly checks"}}
    assert tr.classify_record(entry) == "system"


def test_turn_origin_sdk_is_human() -> None:
    # Owner-level decision (orchestrator, 2026-09-23): a headless/SDK session's operator input
    # is still a human's own words.
    entry = {"turnOrigin": "sdk", "message": {"content": "run the migration"}}
    assert tr.classify_record(entry) == "human"


def test_prompt_source_typed_and_queued_are_human_system_is_system_sdk_is_human() -> None:
    typed = {"promptSource": "typed", "message": {"content": "hi"}}
    queued = {"promptSource": "queued", "message": {"content": "hi"}}
    system = {"promptSource": "system", "message": {"content": "hook output"}}
    sdk = {"promptSource": "sdk", "message": {"content": "hi"}}
    assert tr.classify_record(typed) == "human"
    assert tr.classify_record(queued) == "human"
    assert tr.classify_record(system) == "system"
    assert tr.classify_record(sdk) == "human"


def test_legacy_record_with_no_classifying_field_at_all_is_human() -> None:
    # Rule 9, the final fallback: a pre-`origin` transcript record.
    entry = {"type": "user", "isMeta": False, "message": {"content": "plain legacy text"}}
    assert tr.classify_record(entry) == "human"


# --- is_heartbeat_reply ---


def test_is_heartbeat_reply_exact_match() -> None:
    assert tr.is_heartbeat_reply("janitor heartbeat") is True


def test_is_heartbeat_reply_with_up_to_two_drift_lines() -> None:
    # janitor-heartbeat-protocol.md's own quiet contract: "janitor heartbeat" then drift
    # lines, "adding at most 2 lines" -- so 3 total lines is still the bare quiet reply.
    assert tr.is_heartbeat_reply("janitor heartbeat\ndrift line one\ndrift line two") is True


def test_is_heartbeat_reply_false_when_too_long_or_different() -> None:
    four_lines = "janitor heartbeat\nline1\nline2\nline3"
    assert tr.is_heartbeat_reply(four_lines) is False
    assert tr.is_heartbeat_reply("Reading the TRDD card and dispatching the fix agent.") is False
    assert tr.is_heartbeat_reply("") is False


def test_is_heartbeat_reply_strips_surrounding_whitespace() -> None:
    assert tr.is_heartbeat_reply("  janitor heartbeat  \n") is True
