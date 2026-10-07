"""Tests for the clear-path continuity (TRDD-DS3WDTPV step C2): `lib/session_continuity.py`, the
`HandoffInputs.next_action` rendering, and the post-clear hook's `## Continuity` block.

Every fixture is synthetic (no real transcript, e-mail or prose). Nothing here mocks the unit
under test: transcripts are real JSONL files, the hook runs through its `main()`, and only
`jev_compact.py` is a stub script (same as `test_on_session_start_post_clear_compact.py`).
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import external_clear as ec  # noqa: E402
import jev_compaction_lane as jcl  # noqa: E402
import session_continuity as sc  # noqa: E402
from test_on_session_start_post_clear_compact import (  # type: ignore[import-not-found]  # noqa: E402
    _COMPACTED_DOC,
    _env,
    _import,
    _stub_jev_compact,
    _write_sidecar,
)


def _user(text: str, **extra: object) -> dict:
    return {"type": "user", "message": {"role": "user", "content": text}, **extra}


def _assistant(*blocks: dict) -> dict:
    return {"type": "assistant", "message": {"role": "assistant", "content": list(blocks)}}


def _text(t: str) -> dict:
    return {"type": "text", "text": t}


def _tool_use(name: str, **inp: object) -> dict:
    return {"type": "tool_use", "name": name, "input": inp}


def _heartbeat_turns(n: int) -> list[dict]:
    return [
        e
        for _ in range(n)
        for e in (
            _user("[janitor-heartbeat]\nrun the stub"),
            _assistant(_text("janitor heartbeat")),
        )
    ]


def _write(path: Path, entries: list[dict]) -> str:
    path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n", encoding="utf-8")
    return str(path)


def _incident(tmp_path: Path) -> str:
    """Human question, assistant preface -> tool call -> closing question, then 4 heartbeats."""
    return _write(
        tmp_path / "old.jsonl",
        [
            _user("have you fixed X?"),
            _assistant(_text("Let me check the state first.")),
            _assistant(_tool_use("Bash", command="true")),
            _assistant(_text("X is fixed in the working tree. Shall I publish? reply go to publish.")),
            *_heartbeat_turns(4),
        ],
    )


def test_incident_shape_next_action_quotes_the_closing_question_never_the_heartbeat(tmp_path):
    """Heartbeat turns after the last human turn neither replace last_user nor own_reply."""
    fields = sc.clear_fields(_incident(tmp_path))
    assert fields["last_user"] == "have you fixed X?"
    assert fields["own_reply"].endswith("reply go to publish.")
    assert "Let me check" not in fields["own_reply"], "the LAST text block, not the preface"
    action = sc.next_action(fields)
    assert action is not None
    assert "have you fixed X?" in action and "reply go to publish." in action
    assert "janitor heartbeat" not in action



def test_next_action_continues_in_flight_work_instead_of_asking_and_stopping():
    """A closing question must not park the resumed session: it keeps working, then re-asks."""
    action = sc.next_action({"last_user": "have you fixed X?", "own_reply": "Fixed. Shall I publish?"})
    assert action is not None
    assert "and stop" not in action
    assert "keep doing the steps of that task that do not depend on the answer" in action
    assert "Never take the action the question asks permission for" in action
    assert "If no task was in flight, or your question asked what to work on, ask it again and wait." in action


@pytest.mark.parametrize(
    "noise",
    [
        _user("<task-notification><task-id>t1</task-id></task-notification>"),
        _user("[SYSTEM NOTIFICATION - NOT USER INPUT]\nautomated event"),
        _user("<local-command-stdout>ok</local-command-stdout>"),
        _user("<local-command-caveat>caveat</local-command-caveat>"),
        _user("[Request interrupted by user]"),
        _user("<command-message>clear</command-message>\n<command-name>/clear</command-name>"),
        _user("[janitor-heartbeat]\nrun the stub"),
        _user("synthetic", origin={"kind": "task-notification"}),
        _user("synthetic hidden context", isMeta=True),
        {"type": "attachment", "attachment": {"type": "queued_command", "prompt": "queued text"}},
        {"type": "user", "message": {"role": "user", "content": [{"type": "image", "source": {}}]}},
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "u1", "content": "result"}],
            },
        },
    ],
    ids=[
        "task-notification", "system-notification", "local-stdout", "local-caveat", "interrupt",
        "automation-command", "heartbeat-prompt", "origin-task-notification", "meta",
        "queued-command-attachment", "image-only-paste", "tool-result-carrier",
    ],
)
def test_non_human_records_never_become_last_user(tmp_path, noise):
    """Each non-human shape, placed AFTER a real human turn, leaves last_user untouched."""
    path = _write(tmp_path / "old.jsonl", [_user("real question"), _assistant(_text("real answer")), noise])
    fields = sc.clear_fields(path)
    assert fields["last_user"] == "real question"


def test_non_ascii_truncation_is_character_safe(tmp_path):
    """Long «»/accented text is clipped on characters: still valid, the reply keeps its END."""
    user = "«perché è così» " * 80
    reply = "début… " * 200 + "fin «réponse» finale ✓"
    path = _write(tmp_path / "old.jsonl", [_user(user), _assistant(_text(reply))])
    fields = sc.clear_fields(path)
    assert fields["last_user"].startswith("«perché è così»")
    assert len(fields["last_user"]) <= sc.LAST_USER_MAX_CHARS + 1
    assert fields["own_reply"].endswith("fin «réponse» finale ✓")
    assert len(fields["own_reply"]) <= sc.OWN_REPLY_MAX_CHARS + 1
    for value in fields.values():
        if isinstance(value, str):
            assert "�" not in value
            value.encode("utf-8")


def test_goal_is_the_last_unmet_goal_status(tmp_path):
    """A later met:true goal_status clears the goal; an unmet one is reported."""
    unmet = {"type": "attachment", "attachment": {"type": "goal_status", "met": False, "condition": "ship C2"}}
    met = {"type": "attachment", "attachment": {"type": "goal_status", "met": True, "condition": "ship C2"}}
    assert sc.clear_fields(_write(tmp_path / "a.jsonl", [_user("go"), unmet]))["goal"] == "ship C2"
    assert sc.clear_fields(_write(tmp_path / "b.jsonl", [_user("go"), unmet, met]))["goal"] == ""


def test_open_tasks_skip_completed_and_a_missing_dir_is_silent(tmp_path, monkeypatch):
    """Subjects of non-completed task files; no tasks dir -> [] and no fallback to another list."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    old = tmp_path / "abc-123.jsonl"
    _write(old, [_user("go")])
    assert sc.clear_fields(str(old))["open_tasks"] == []
    other = tmp_path / "home" / ".claude" / "tasks" / "some-other-session"
    other.mkdir(parents=True)
    (other / "1.json").write_text(json.dumps({"id": "1", "subject": "foreign", "status": "pending"}))
    assert sc.clear_fields(str(old))["open_tasks"] == []
    mine = tmp_path / "home" / ".claude" / "tasks" / "abc-123"
    mine.mkdir(parents=True)
    (mine / "1.json").write_text(json.dumps({"id": "1", "subject": "done one", "status": "completed"}))
    (mine / "2.json").write_text(json.dumps({"id": "2", "subject": "write tests", "status": "in_progress"}))
    (mine / "10.json").write_text(json.dumps({"id": "10", "subject": "ship it", "status": "pending"}))
    assert sc.clear_fields(str(old))["open_tasks"] == ["write tests", "ship it"]


def test_plan_file_only_when_named_in_the_transcript_and_existing(tmp_path, monkeypatch):
    """A plan path counts only if the old transcript names it (attachment or ExitPlanMode) and it exists."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    plans = tmp_path / "home" / ".claude" / "plans"
    plans.mkdir(parents=True)
    named = plans / "named.md"
    named.write_text("plan")
    (plans / "newest-unnamed.md").write_text("other plan")
    ref = {"type": "attachment", "attachment": {"type": "plan_file_reference", "planFilePath": str(named)}}
    assert sc.clear_fields(_write(tmp_path / "a.jsonl", [_user("go"), ref]))["plan_file"] == str(named)
    exit_plan = _assistant(_tool_use("ExitPlanMode", planFilePath=str(named)))
    assert sc.clear_fields(_write(tmp_path / "b.jsonl", [_user("go"), exit_plan]))["plan_file"] == str(named)
    assert sc.clear_fields(_write(tmp_path / "c.jsonl", [_user("go")]))["plan_file"] == ""
    gone = {"type": "attachment", "attachment": {"type": "plan_file_reference", "planFilePath": str(plans / "gone.md")}}
    assert sc.clear_fields(_write(tmp_path / "d.jsonl", [_user("go"), gone]))["plan_file"] == ""


def test_render_block_drops_lowest_priority_lines_to_fit_and_names_files_unread():
    """Over budget, trailing lines go first; files/plan carry the 'mentioned, not read' wording."""
    record = {
        "goal": "g", "open_tasks": ["t1"], "active_skills": ["ponytail"],
        "plan_file": "/p/plan.md", "background_agents": [{"agentId": "a1", "description": "d"}],
        "open_files": ["/p/x.py"],
    }
    full = sc.render_block(record)
    assert "Re-invoke skills: ponytail" in full
    assert "Plan file (mentioned, not read): /p/plan.md" in full
    assert "Open files (mentioned, not read): /p/x.py" in full
    small = sc.render_block(record, max_bytes=len(full.encode()) - 5)
    assert "Goal (not yet met): g" in small and "Open files" not in small
    assert sc.render_block({}) == ""


def test_next_action_renders_in_the_template_and_falls_back_to_card_state_when_unset():
    """HandoffInputs.next_action replaces the card-STATE pointer; unset keeps the old text."""
    card = [("ABCD1234", "dev", "some card")]
    with_action = ec.compose_template_handoff(
        ec.HandoffInputs(cards=card, next_action="The user's last message was «q»."), now_iso="t",
    )
    assert "The user's last message was «q»." in with_action
    assert "Read the `## STATE` block" not in with_action
    assert "Read the `## STATE` block" in ec.compose_template_handoff(ec.HandoffInputs(cards=card), now_iso="t")


def _run_hook(tmp_path, monkeypatch, transcript: str, *, doc: str, sidecar: bool = True) -> str:
    project_dir = tmp_path / "project"
    project_dir.mkdir(exist_ok=True)
    plugin_root = tmp_path / "plugin"
    _env(tmp_path, monkeypatch, project_dir=project_dir, plugin_root=plugin_root)
    monkeypatch.setenv("TMUX_PANE", "%7")
    sd = project_dir / ".janitor" / "state"
    if sidecar:
        _write_sidecar(sd, {"TMUX_PANE": "%7"}, transcript=transcript)
    _stub_jev_compact(plugin_root, tmp_path / "argv.txt", exit_code=0, out_text=doc)
    mod = _import()
    monkeypatch.setattr(mod, "_payload", lambda: {"source": "clear"})
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert mod.main() == 0
    return buf.getvalue()


def test_hook_injects_next_action_and_continuity_block_ahead_of_the_jev_text(tmp_path, monkeypatch):
    """Sidecar present: NEXT ACTION quotes the reply, the block carries goal/tasks/skills, before Jev text."""
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))
    stem = "old"
    tasks = tmp_path / "fake-home" / ".claude" / "tasks" / stem
    tasks.mkdir(parents=True)
    (tasks / "1.json").write_text(json.dumps({"id": "1", "subject": "write tests", "status": "pending"}))
    goal = {"type": "attachment", "attachment": {"type": "goal_status", "met": False, "condition": "ship C2"}}
    transcript = _write(
        tmp_path / f"{stem}.jsonl",
        [
            _user("have you fixed X?"),
            _assistant(_tool_use("Skill", command="ponytail")),
            _assistant(_text("Fixed. Shall I publish? reply go to publish.")),
            goal,
            *_heartbeat_turns(4),
        ],
    )
    out = _run_hook(tmp_path, monkeypatch, transcript, doc=_COMPACTED_DOC)
    assert "have you fixed X?" in out and "reply go to publish." in out
    assert "janitor heartbeat" not in out
    assert "## Continuity" in out
    assert "Goal (not yet met): ship C2" in out
    assert "Open tasks: write tests" in out
    assert "Re-invoke skills: ponytail" in out
    assert out.index("## Continuity") < out.index("## Compacted context")


def test_hook_block_survives_a_huge_jev_text_within_budget(tmp_path, monkeypatch):
    """A 30 KB compaction cannot squeeze out the block, and the whole injection stays bounded."""
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))
    transcript = _write(tmp_path / "old.jsonl", [_user("go on"), _assistant(_text("ok, doing it"))])
    goal = {"type": "attachment", "attachment": {"type": "goal_status", "met": False, "condition": "ship C2"}}
    with open(transcript, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(goal) + "\n")
    huge = (
        "# Compacted context (Jev compaction)\n\n## Kept items\n" + "some kept text\n" * 2500
        + '\n\npointers expand with: uv run --script "$CLAUDE_PLUGIN_ROOT/scripts/jev_compact.py" '
        "expand --transcript /tmp/x <id>"
    )
    out = _run_hook(tmp_path, monkeypatch, transcript, doc=huge)
    assert "Goal (not yet met): ship C2" in out
    assert "pointers expand with:" in out
    assert len(out.encode("utf-8")) <= 9000


def test_no_sidecar_means_no_continuity_block(tmp_path, monkeypatch):
    """A user-typed /clear (no sidecar) injects nothing from this hook, so no block either."""
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))
    transcript = _write(tmp_path / "old.jsonl", [_user("go"), _assistant(_text("ok"))])
    out = _run_hook(tmp_path, monkeypatch, transcript, doc=_COMPACTED_DOC, sidecar=False)
    assert "## Continuity" not in out
    assert out == ""


# --- issue 338: the owner's last messages survive consecutive clears ---------------------------
# Record shapes below are copied from real cleared-and-resumed transcripts (2026-10-07), with the
# private text replaced: the plugin-qualified arm/resume command wrappers (origin human), the
# local-command-caveat (isMeta), the skill-body expansion (isMeta) and the heartbeat prompt.

_ARM = _user(
    "<command-message>ai-maestro-janitor:janitor-arm</command-message>\n"
    "<command-name>/ai-maestro-janitor:janitor-arm</command-name>",
    origin={"kind": "human"}, turnOrigin="human",
)
_RESUME = _user(
    "<command-message>ai-maestro-janitor:janitor-resume</command-message>\n"
    "<command-name>/ai-maestro-janitor:janitor-resume</command-name>",
    origin={"kind": "human"}, turnOrigin="human",
)
_CAVEAT = _user("<local-command-caveat>caveat</local-command-caveat>", isMeta=True)


def _stood_down_session(path: Path) -> str:
    """A resumed session in which no human typed: injected commands, heartbeats, a stand-down."""
    return _write(
        path,
        [_CAVEAT, _ARM, _user("Base directory for this skill: x", isMeta=True), _RESUME,
         _assistant(_text("There's nothing to resume.")), *_heartbeat_turns(2)],
    )


def _stamped(text: str, ts: str) -> dict:
    return _user(text, timestamp=ts)


def _transcript_a(tmp_path: Path) -> str:
    return _write(
        tmp_path / "sess-a.jsonl",
        [_stamped("fix issue 338 now", "2026-10-07T19:00:00.000Z"), _assistant(_text("on it")),
         _stamped("and why two clears?", "2026-10-07T19:05:00.000Z"), _assistant(_text("measuring it")),
         *_heartbeat_turns(1)],
    )


def test_clear_writes_the_lineage_record_under_both_session_ids(tmp_path):
    """The two human messages and the reply land in owner-messages/<id>.json for old and new id."""
    sd = tmp_path / "sd"
    fields = sc.clear_fields(_transcript_a(tmp_path), state_dir=sd, new_session_id="sess-b")
    assert [m["text"] for m in fields["owner_messages"]] == ["fix issue 338 now", "and why two clears?"]
    for sid in ("sess-a", "sess-b"):
        rec = json.loads((sd / "owner-messages" / f"{sid}.json").read_text(encoding="utf-8"))
        assert [m["text"] for m in rec["messages"]] == ["fix issue 338 now", "and why two clears?"]
        assert rec["own_reply"] == "measuring it" and rec["origin_session"] == "sess-a"


def test_second_clear_with_no_human_message_carries_the_first_sessions_messages(tmp_path):
    """B has only injected records and a stand-down: A's messages and A's reply are carried and quoted."""
    sd = tmp_path / "sd"
    sc.clear_fields(_transcript_a(tmp_path), state_dir=sd, new_session_id="sess-b")
    fields = sc.clear_fields(
        _stood_down_session(tmp_path / "sess-b.jsonl"), state_dir=sd, new_session_id="sess-c",
    )
    assert [m["text"] for m in fields["owner_messages"]] == ["fix issue 338 now", "and why two clears?"]
    assert fields["own_reply"] == "measuring it", "B's stand-down must not become the reply"
    assert fields["carried_from"] == {"session_id": "sess-a", "ts": "2026-10-07T19:05:00.000Z"}
    action = sc.next_action(fields)
    assert action is not None
    assert "earlier session" in action and "fix issue 338 now" in action and "and why two clears?" in action
    assert "measuring it" in action and "nothing to resume" not in action.split("A previous session")[0]
    assert "open-board counts by column" in action and "standing assignment" not in action


def test_third_hop_still_carries_the_first_sessions_messages(tmp_path):
    """C (again no human message) still hands A's messages on to D."""
    sd = tmp_path / "sd"
    sc.clear_fields(_transcript_a(tmp_path), state_dir=sd, new_session_id="sess-b")
    sc.clear_fields(_stood_down_session(tmp_path / "sess-b.jsonl"), state_dir=sd, new_session_id="sess-c")
    fields = sc.clear_fields(_stood_down_session(tmp_path / "sess-c.jsonl"), state_dir=sd, new_session_id="sess-d")
    assert fields["owner_messages"][0]["text"] == "fix issue 338 now"
    assert fields["own_reply"] == "measuring it" and fields["carried_from"]["session_id"] == "sess-a"
    assert (sd / "owner-messages" / "sess-d.json").is_file()


def test_new_human_message_appends_and_only_the_last_three_are_kept(tmp_path):
    """A later session with its own human message: stored + new, trimmed to three, new reply wins."""
    sd = tmp_path / "sd"
    sc.clear_fields(_transcript_a(tmp_path), state_dir=sd, new_session_id="sess-b")
    later = _write(
        tmp_path / "sess-b.jsonl",
        [_ARM, _stamped("third", "2026-10-07T20:00:00.000Z"), _assistant(_text("r3")),
         _stamped("fourth", "2026-10-07T20:10:00.000Z"), _assistant(_text("r4"))],
    )
    fields = sc.clear_fields(later, state_dir=sd, new_session_id="sess-c")
    assert [m["text"] for m in fields["owner_messages"]] == ["and why two clears?", "third", "fourth"]
    assert fields["own_reply"] == "r4" and "carried_from" not in fields
    action = sc.next_action(fields)
    assert action is not None and "most recent messages were" in action and "fourth" in action


def test_unrelated_sessions_in_one_state_dir_do_not_see_each_other(tmp_path):
    """Records are keyed by session lineage: an unrelated cleared session carries nothing."""
    sd = tmp_path / "sd"
    sc.clear_fields(_transcript_a(tmp_path), state_dir=sd, new_session_id="sess-b")
    fields = sc.clear_fields(
        _stood_down_session(tmp_path / "other.jsonl"), state_dir=sd, new_session_id="other-2",
    )
    assert fields["last_user"] == "" and "carried_from" not in fields
    assert sc.next_action(fields) is None


def test_without_state_dir_nothing_is_read_or_written(tmp_path):
    """state_dir=None keeps today's behaviour: the cleared transcript alone, no files."""
    fields = sc.clear_fields(_transcript_a(tmp_path))
    assert fields["last_user"] == "and why two clears?" and "carried_from" not in fields
    assert not list(tmp_path.rglob("owner-messages"))


def test_corrupt_lineage_record_means_no_carry_and_no_exception(tmp_path):
    """A garbage record file is ignored: the fresh session simply gets no carried messages."""
    sd = tmp_path / "sd"
    (sd / "owner-messages").mkdir(parents=True)
    (sd / "owner-messages" / "sess-b.json").write_text("{not json", encoding="utf-8")
    fields = sc.clear_fields(
        _stood_down_session(tmp_path / "sess-b.jsonl"), state_dir=sd, new_session_id="sess-c",
    )
    assert fields["last_user"] == "" and "carried_from" not in fields
    assert sc.owner_record(sd, "sess-b") is None


def test_injected_command_records_are_never_human_text():
    """The real arm/resume/caveat/heartbeat shapes of a resumed session are not human input."""
    for entry in (_ARM, _RESUME, _CAVEAT, _user("[janitor-heartbeat]\nrun the stub")):
        assert sc._human_text(entry) == ""
