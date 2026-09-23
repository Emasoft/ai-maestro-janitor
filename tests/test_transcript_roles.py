"""Tests for scripts/lib/transcript_roles.py (TRDD-RAEGS1D5, orchestrator scope extension).

One test per measured record class from reports/compaction-replacement/
20260923_200805+0200-jev-reference-gap-analysis.md §2.1 -- each entry below mirrors the exact
field combination that table measured on real transcripts, not a guessed shape.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import transcript_roles as tr  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_warned_unknown_origin_kinds(monkeypatch: pytest.MonkeyPatch) -> None:
    # Coordinator correction (3): `_warned_unknown_origin_kinds` is module-level, process-
    # lifetime state -- without a reset, whichever test runs first "claims" a given
    # origin.kind value and every later test using the same literal silently stops seeing a
    # stderr line, making pass/fail depend on test execution order. Reset it fresh per test.
    monkeypatch.setattr(tr, "_warned_unknown_origin_kinds", set())


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


def test_typed_slash_command_with_args_and_human_origin_is_human() -> None:
    # TRDD-RAEGS1D5 defect 1 (review): a typed slash command like `/loop 5m <prompt>` wraps
    # in `<command-message>` (matched by rule 4's generic system-prefix list) but ALSO carries
    # `<command-name>` and `<command-args>`, with origin.kind "human" -- measured on real
    # transcripts, this is the owner's own instruction, not harness noise.
    entry = {
        "origin": {"kind": "human"},
        "message": {
            "content": (
                "<command-message>loop is running…</command-message>\n"
                "<command-name>/loop</command-name>\n"
                "<command-args>5m fix the failing test</command-args>"
            )
        },
    }
    assert tr.classify_record(entry) == "human"


def test_command_message_without_command_name_stays_system() -> None:
    # Same wrapper text, but no <command-name> tag at all -- not a typed slash command, so
    # the generic system-prefix rule still applies (unlike the test above). Coordinator
    # correction (4): this exact shape (`<command-message>` with no `<command-name>` at all)
    # was NOT observed in either real transcript inspected for this fix -- every measured
    # `<command-message>` record carried a `<command-name>`. This test is defensive, pinning
    # the fallback behaviour for a shape that might exist in an older/different transcript
    # rather than one confirmed in the corpus.
    entry = {
        "origin": {"kind": "human"},
        "message": {"content": "<command-message>some-command</command-message>"},
    }
    assert tr.classify_record(entry) == "system"


def test_automation_command_without_args_is_system() -> None:
    # Coordinator correction (2): the janitor types `/janitor-resume` (plugin-qualified:
    # `/ai-maestro-janitor:janitor-resume`) into the pane itself -- recorded identically to an
    # owner-typed command, with no `<command-args>` -- so it must be "system", not "human", or
    # it fills an unattended session's digest with the janitor's own automation.
    entry = {
        "origin": {"kind": "human"},
        "message": {
            "content": (
                "<command-message>resuming…</command-message>\n"
                "<command-name>/ai-maestro-janitor:janitor-resume</command-name>"
            )
        },
    }
    assert tr.classify_record(entry) == "system"


def test_automation_command_bare_name_no_args_is_system() -> None:
    # Same as above, bare (non-plugin-qualified) form.
    entry = {
        "origin": {"kind": "human"},
        "message": {
            "content": (
                "<command-message>resuming…</command-message>\n"
                "<command-name>/janitor-resume</command-name>"
            )
        },
    }
    assert tr.classify_record(entry) == "system"


def test_clear_with_no_args_is_system() -> None:
    entry = {
        "origin": {"kind": "human"},
        "message": {
            "content": (
                "<command-message>clearing…</command-message>\n<command-name>/clear</command-name>"
            )
        },
    }
    assert tr.classify_record(entry) == "system"


def test_task_command_with_args_is_human() -> None:
    # `/task` is not in the automation list at all, so args presence doesn't even matter --
    # it is "human" the same way `/loop` is in the test above.
    entry = {
        "origin": {"kind": "human"},
        "message": {
            "content": (
                "<command-message>running…</command-message>\n"
                "<command-name>/task</command-name>\n"
                "<command-args>fix the failing test</command-args>"
            )
        },
    }
    assert tr.classify_record(entry) == "human"


def test_automation_command_with_real_args_is_still_system() -> None:
    # Coordinator correction (4), superseding correction (2)'s args tie-breaker: the janitor
    # itself types `/reload-plugins --force` and `/janitor-compact-context --hard` -- an
    # automation-named command is "system" by NAME ALONE, regardless of args. A former
    # version of this test asserted "human" here; that assertion was the defect this
    # correction fixes.
    entry = {
        "origin": {"kind": "human"},
        "message": {
            "content": (
                "<command-message>arming…</command-message>\n"
                "<command-name>/janitor-arm</command-name>\n"
                "<command-args>--scope project</command-args>"
            )
        },
    }
    assert tr.classify_record(entry) == "system"


def test_reload_plugins_with_force_flag_is_system() -> None:
    # The exact example from the coordinator's rationale: `/reload-plugins --force`.
    entry = {
        "origin": {"kind": "human"},
        "message": {
            "content": (
                "<command-message>reloading…</command-message>\n"
                "<command-name>/reload-plugins</command-name>\n"
                "<command-args>--force</command-args>"
            )
        },
    }
    assert tr.classify_record(entry) == "system"


# --- derive the plugin's OWN command names and assert each is always "system" ---

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
_SKILL_NAME_RE = re.compile(r"^name:\s*(\S+)\s*$", re.MULTILINE)


def _plugin_command_names() -> list[str]:
    """Every command name this plugin ships: `skills/*/SKILL.md`'s frontmatter `name:`, plus
    `commands/*.md` filenames (a Claude Code command's name is its filename stem) when that
    directory exists. TRDD-RAEGS1D5 coordinator correction (5): derived from the actual
    shipped files, not hand-copied, so a new command can never silently slip past the
    automation-name allowlist without this test catching it."""
    names: list[str] = []
    for skill_md in sorted((_PLUGIN_ROOT / "skills").glob("*/SKILL.md")):
        text = skill_md.read_text(encoding="utf-8")
        # Frontmatter is the first `---`-delimited block; search only inside it so a stray
        # "name:" mentioned later in the body can never be mistaken for the skill's own name.
        frontmatter_end = text.find("\n---", 3)
        frontmatter = text[:frontmatter_end] if frontmatter_end != -1 else text
        match = _SKILL_NAME_RE.search(frontmatter)
        if match:
            names.append(match.group(1))
    commands_dir = _PLUGIN_ROOT / "commands"
    if commands_dir.is_dir():
        names.extend(p.stem for p in sorted(commands_dir.glob("*.md")))
    return names


def _command_message_entry(command_name: str, *, with_args: bool) -> dict:
    content = f"<command-message>running…</command-message>\n<command-name>{command_name}</command-name>"
    if with_args:
        content += "\n<command-args>some args</command-args>"
    return {"origin": {"kind": "human"}, "message": {"content": content}}


def test_every_shipped_plugin_command_classifies_as_system() -> None:
    names = _plugin_command_names()
    assert names, "expected at least one skill/command name -- an empty list would make this test vacuous"
    # Review finding: `assert names` only catches TOTAL silent loss (the regex matching
    # nothing anywhere), not PARTIAL loss -- a `name:` line the regex fails on (e.g. a
    # trailing same-line comment breaking the `\s*$` end-anchor) would silently drop just
    # that one skill from the list instead of failing this test, exactly the "new command
    # slips past unnoticed" scenario this test exists to prevent. Pin the derived count
    # against the actual file count so a partial miss fails loudly instead of quietly.
    skill_file_count = len(list((_PLUGIN_ROOT / "skills").glob("*/SKILL.md")))
    assert len(names) >= skill_file_count, (
        f"derived {len(names)} command name(s) but found {skill_file_count} SKILL.md "
        "file(s) -- the frontmatter regex silently failed to match one or more of them"
    )
    for name in names:
        for qualified in (name, f"ai-maestro-janitor:{name}"):
            for prefixed in (qualified, f"/{qualified}"):
                for with_args in (False, True):
                    entry = _command_message_entry(prefixed, with_args=with_args)
                    role = tr.classify_record(entry)
                    assert role == "system", (
                        f"{prefixed!r} (with_args={with_args}) classified {role!r}, "
                        "not 'system' -- a shipped plugin command must never silently "
                        "count as the owner's own words"
                    )


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


def test_unknown_origin_kind_is_never_human_and_is_named_on_stderr(capsys) -> None:
    # TRDD-RAEGS1D5 defect 2 (review): an explicit origin.kind this classifier doesn't
    # recognise used to fall through to turnOrigin -> promptSource -> the final "human"
    # fallback, so a future system-authored kind would silently count as the owner's own
    # words. It must now route to "notification" and be named on stderr, even when a later
    # field (turnOrigin here) would have said "human". Uses a value OTHER than "unclassified"
    # -- that one is a real, frequent, deliberately-non-deciding value (coordinator
    # correction below), not an example of a genuinely unrecognised kind.
    entry = {
        "isMeta": False, "origin": {"kind": "some-future-kind"}, "turnOrigin": "human",
        "message": {"content": "hi"},
    }
    assert tr.classify_record(entry) == "notification"
    assert "some-future-kind" in capsys.readouterr().err


def test_unknown_origin_kind_is_named_on_stderr_only_once_per_process(capsys) -> None:
    # Coordinator correction: printing unconditionally floods stderr in jev_compaction.py and
    # the hooks on a bulk transcript scan -- at most one stderr line per distinct unrecognised
    # value per process, tracked in a module-level set.
    entry = {"isMeta": False, "origin": {"kind": "yet-another-kind"}, "message": {"content": "x"}}
    assert tr.classify_record(entry) == "notification"
    assert tr.classify_record(entry) == "notification"
    err_lines = capsys.readouterr().err.splitlines()
    assert len([line for line in err_lines if "yet-another-kind" in line]) == 1


def test_unclassified_origin_kind_is_no_decision_and_falls_through(capsys) -> None:
    # Coordinator correction (2026-09-23): origin.kind "unclassified" is measured on 7,190
    # real records, mostly list/tool_result carriers -- it means "origin gives no decision",
    # NOT an unrecognised kind, so it must fall through to turnOrigin/promptSource/legacy
    # exactly like a missing `kind`, and must never print to stderr or become "notification".
    entry = {
        "isMeta": False, "origin": {"kind": "unclassified"}, "promptSource": "typed",
        "message": {"content": "hi"},
    }
    assert tr.classify_record(entry) == "human"
    assert capsys.readouterr().err == ""


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
