"""Tests for the USER-MEMORY UserPromptSubmit hook (TRDD-4334aad0).

This file pins the PRIVACY BOUNDARY — the load-bearing security property — by
running the real hook script (`on-prompt-submit-user-mem.py`) as a subprocess
with a crafted stdin JSON and asserting on its stdout JSON contract:

  /to-user-mem      → prompt is BLOCKED (erased from agent context); the saved
                      text lands on disk and appears in NO agent-context field
                      of the hook output (no additionalContext, no plain stdout).
  /search-user-mem  → prompt is BLOCKED; results reach the user ONLY via
                      `systemMessage`; they appear in NO agent-context field.
  /share-user-mem N → the ONE explicit gate: memory #N's text is injected into
                      the agent context via `additionalContext`.
  anything else     → the hook is a no-op (exit 0, empty stdout) — fast path.

The Claude Code documented semantics this relies on:
  - UserPromptSubmit `{"decision":"block"}` "Blocks prompt processing and erases
    the prompt" — so a blocked prompt never enters the agent context/transcript.
  - `systemMessage` is "shown to the user" — user-facing, NOT agent context.
  - `hookSpecificOutput.additionalContext` (and plain non-JSON stdout) DO enter
    the agent context — used ONLY for /share-user-mem.

HOME is redirected to a tmp dir so the real per-project memory store is never
touched; CLAUDE_PROJECT_DIR points at a tmp project.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_HOOK = _PROJECT_ROOT / "scripts" / "hooks" / "on-prompt-submit-user-mem.py"
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import user_mem_lib  # noqa: E402

# Fields the docs route INTO the agent's context window. The saved memory text
# / search results must NEVER appear in any of these.
_AGENT_CONTEXT_FIELDS = ("additionalContext",)


def _run_hook(payload: dict, env_extra: dict, project: Path, home: Path) -> tuple[int, str, str]:
    """Invoke the hook script with `payload` on stdin; return (rc, stdout, stderr)."""
    import os

    env = dict(os.environ)
    env["HOME"] = str(home)
    env["CLAUDE_PROJECT_DIR"] = str(project)
    env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _resolve(home: Path, project: Path) -> Path:
    # Resolve the store dir the same way the hook will, with HOME pinned to tmp.
    import os

    old_home = os.environ.get("HOME")
    os.environ["HOME"] = str(home)
    try:
        return user_mem_lib.resolve_user_mem_dir(project_dir=str(project))
    finally:
        if old_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = old_home


# --------------------------------------------------------------------------
# fast path: non-command prompts are a no-op
# --------------------------------------------------------------------------


def test_non_command_prompt_is_noop(tmp_path):
    """An ordinary prompt produces exit 0 and empty stdout — the hook stays out of the way."""
    rc, out, _err = _run_hook(
        {"hook_event_name": "UserPromptSubmit", "prompt": "what is the capital of France?"},
        {},
        tmp_path / "proj",
        tmp_path / "home",
    )
    assert rc == 0
    assert out.strip() == ""


def test_empty_prompt_is_noop(tmp_path):
    """An empty prompt is a no-op (no crash, no output)."""
    rc, out, _err = _run_hook(
        {"hook_event_name": "UserPromptSubmit", "prompt": ""},
        {},
        tmp_path / "proj",
        tmp_path / "home",
    )
    assert rc == 0
    assert out.strip() == ""


def test_lookalike_command_is_not_intercepted(tmp_path):
    """`/to-user-memory ...` (a different word) is NOT treated as /to-user-mem."""
    rc, out, _err = _run_hook(
        {"hook_event_name": "UserPromptSubmit", "prompt": "/to-user-memory please"},
        {},
        tmp_path / "proj",
        tmp_path / "home",
    )
    assert rc == 0
    assert out.strip() == ""


# --------------------------------------------------------------------------
# /to-user-mem <text> — save + PRIVACY
# --------------------------------------------------------------------------


def test_to_user_mem_with_text_saves_and_blocks(tmp_path):
    """`/to-user-mem <text>` blocks the prompt and writes the text to the user-mem store."""
    secret = "my api key rotation cadence is every 30 days"
    rc, out, _err = _run_hook(
        {"hook_event_name": "UserPromptSubmit", "prompt": f"/to-user-mem {secret}"},
        {},
        tmp_path / "proj",
        tmp_path / "home",
    )
    assert rc == 0
    obj = json.loads(out)
    assert obj.get("decision") == "block"  # prompt erased from agent context
    # The memory landed on disk.
    store = user_mem_lib.UserMemStore(_resolve(tmp_path / "home", tmp_path / "proj"))
    assert store.read(1) == secret


def test_to_user_mem_text_is_not_in_any_agent_context_field(tmp_path):
    """PRIVACY: the saved text appears in NO agent-context field of the hook output."""
    secret = "PRIVATE-TOKEN-abc123-do-not-leak"
    _rc, out, _err = _run_hook(
        {"hook_event_name": "UserPromptSubmit", "prompt": f"/to-user-mem {secret}"},
        {},
        tmp_path / "proj",
        tmp_path / "home",
    )
    obj = json.loads(out)
    # decision:block erases the prompt; the secret must not be smuggled back in
    # via additionalContext (which the docs DO route to the model).
    for field in _AGENT_CONTEXT_FIELDS:
        assert secret not in json.dumps(obj.get("hookSpecificOutput", {}))
        assert secret not in str(obj.get(field, ""))
    # Belt-and-braces: the secret must not be anywhere the model reads. The ONLY
    # permitted echo is a user-facing confirmation, which by design says
    # "content withheld" and never the text itself.
    reason = str(obj.get("reason", ""))
    sysmsg = str(obj.get("systemMessage", ""))
    assert secret not in reason
    assert secret not in sysmsg


def test_to_user_mem_confirmation_reports_number_and_withholding(tmp_path):
    """The user-facing confirmation reports the immutable number and that content was withheld."""
    _rc, out, _err = _run_hook(
        {"hook_event_name": "UserPromptSubmit", "prompt": "/to-user-mem something to remember"},
        {},
        tmp_path / "proj",
        tmp_path / "home",
    )
    obj = json.loads(out)
    # The confirmation goes to the user via systemMessage and/or reason.
    confirmation = str(obj.get("systemMessage", "")) + str(obj.get("reason", ""))
    assert "#1" in confirmation
    assert "withheld" in confirmation.lower() or "private" in confirmation.lower()


def test_to_user_mem_bare_uses_previous_user_message(tmp_path):
    """Bare `/to-user-mem` saves the WHOLE previous user message read from the transcript."""
    transcript = tmp_path / "t.jsonl"
    prev = "this is the message I want filed as a memory"
    transcript.write_text(
        "\n".join(
            json.dumps(e)
            for e in (
                {"type": "user", "message": {"role": "user", "content": prev}},
                {"type": "user", "message": {"role": "user", "content": "/to-user-mem"}},
            )
        )
        + "\n",
        encoding="utf-8",
    )
    rc, out, _err = _run_hook(
        {
            "hook_event_name": "UserPromptSubmit",
            "prompt": "/to-user-mem",
            "transcript_path": str(transcript),
        },
        {},
        tmp_path / "proj",
        tmp_path / "home",
    )
    assert rc == 0
    obj = json.loads(out)
    assert obj.get("decision") == "block"
    store = user_mem_lib.UserMemStore(_resolve(tmp_path / "home", tmp_path / "proj"))
    assert store.read(1) == prev


def test_to_user_mem_bare_no_previous_message_saves_nothing(tmp_path):
    """Bare `/to-user-mem` with no recoverable previous message blocks but saves nothing."""
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(
        json.dumps({"type": "user", "message": {"role": "user", "content": "/to-user-mem"}}) + "\n",
        encoding="utf-8",
    )
    rc, out, _err = _run_hook(
        {
            "hook_event_name": "UserPromptSubmit",
            "prompt": "/to-user-mem",
            "transcript_path": str(transcript),
        },
        {},
        tmp_path / "proj",
        tmp_path / "home",
    )
    assert rc == 0
    obj = json.loads(out)
    assert obj.get("decision") == "block"  # still erased from agent context
    store = user_mem_lib.UserMemStore(_resolve(tmp_path / "home", tmp_path / "proj"))
    assert store.read(1) is None  # nothing was saved


# --------------------------------------------------------------------------
# /search-user-mem <query> — search + PRIVACY
# --------------------------------------------------------------------------


def _seed(home: Path, project: Path, texts: list[str]) -> user_mem_lib.UserMemStore:
    store = user_mem_lib.UserMemStore(_resolve(home, project))
    for t in texts:
        store.save(t)
    return store


def test_search_blocks_and_returns_results_via_systemMessage(tmp_path):
    """`/search-user-mem` blocks the prompt and emits numbered results via systemMessage only."""
    home, proj = tmp_path / "home", tmp_path / "proj"
    _seed(home, proj, ["keychain rotation cadence", "coffee preferences", "deploy keychain check"])
    rc, out, _err = _run_hook(
        {"hook_event_name": "UserPromptSubmit", "prompt": "/search-user-mem +keychain -coffee"},
        {},
        proj,
        home,
    )
    assert rc == 0
    obj = json.loads(out)
    assert obj.get("decision") == "block"
    sysmsg = str(obj.get("systemMessage", ""))
    # Results are present in systemMessage, numbered.
    assert "#1" in sysmsg
    assert "#3" in sysmsg
    assert "#2" not in sysmsg  # excluded by -coffee


def test_search_results_not_in_agent_context_fields(tmp_path):
    """PRIVACY: search results appear ONLY in systemMessage, never in an agent-context field."""
    home, proj = tmp_path / "home", tmp_path / "proj"
    marker = "UNIQUEMARKERWORD"
    _seed(home, proj, [f"a memory containing {marker} inside it"])
    _rc, out, _err = _run_hook(
        {"hook_event_name": "UserPromptSubmit", "prompt": f"/search-user-mem {marker}"},
        {},
        proj,
        home,
    )
    obj = json.loads(out)
    # The result content must NOT be in additionalContext / hookSpecificOutput.
    assert marker not in json.dumps(obj.get("hookSpecificOutput", {}))
    assert marker not in str(obj.get("reason", ""))
    # It IS allowed in systemMessage (user-facing only).
    assert marker in str(obj.get("systemMessage", ""))


def test_search_no_match_reports_zero_results(tmp_path):
    """A no-match search still blocks and tells the user zero results (no crash)."""
    home, proj = tmp_path / "home", tmp_path / "proj"
    _seed(home, proj, ["alpha beta"])
    rc, out, _err = _run_hook(
        {"hook_event_name": "UserPromptSubmit", "prompt": "/search-user-mem +zzznotfound"},
        {},
        proj,
        home,
    )
    assert rc == 0
    obj = json.loads(out)
    assert obj.get("decision") == "block"
    assert "0" in str(obj.get("systemMessage", "")) or "no" in str(obj.get("systemMessage", "")).lower()


# --------------------------------------------------------------------------
# /share-user-mem <number> — the explicit gate INTO agent context
# --------------------------------------------------------------------------


def test_share_injects_memory_into_agent_context(tmp_path):
    """`/share-user-mem N` injects memory #N's text into the agent context via additionalContext."""
    home, proj = tmp_path / "home", tmp_path / "proj"
    text = "the shared memory body that the agent should now see"
    _seed(home, proj, ["unrelated", text])  # text is #2
    rc, out, _err = _run_hook(
        {"hook_event_name": "UserPromptSubmit", "prompt": "/share-user-mem 2"},
        {},
        proj,
        home,
    )
    assert rc == 0
    obj = json.loads(out)
    # The share path is the ONE place additionalContext carries a memory.
    ac = obj.get("hookSpecificOutput", {}).get("additionalContext", "")
    assert text in ac
    # It must NOT also block — the share is meant to reach the model.
    assert obj.get("decision") != "block"


def test_share_unknown_number_blocks_and_does_not_inject(tmp_path):
    """`/share-user-mem N` for a missing N blocks (tells the user) and injects NOTHING."""
    home, proj = tmp_path / "home", tmp_path / "proj"
    _seed(home, proj, ["only one memory"])  # #1 exists; #999 does not
    rc, out, _err = _run_hook(
        {"hook_event_name": "UserPromptSubmit", "prompt": "/share-user-mem 999"},
        {},
        proj,
        home,
    )
    assert rc == 0
    obj = json.loads(out)
    # No memory body injected.
    ac = obj.get("hookSpecificOutput", {}).get("additionalContext", "")
    assert ac == "" or "999" in ac and "not found" in ac.lower()
    # Blocked so the (useless) prompt is erased.
    assert obj.get("decision") == "block"


def test_share_non_numeric_argument_blocks(tmp_path):
    """`/share-user-mem notanumber` blocks with a usage hint and injects nothing."""
    home, proj = tmp_path / "home", tmp_path / "proj"
    _seed(home, proj, ["a memory"])
    rc, out, _err = _run_hook(
        {"hook_event_name": "UserPromptSubmit", "prompt": "/share-user-mem notanumber"},
        {},
        proj,
        home,
    )
    assert rc == 0
    obj = json.loads(out)
    ac = obj.get("hookSpecificOutput", {}).get("additionalContext", "")
    assert "a memory" not in ac
    assert obj.get("decision") == "block"


# --------------------------------------------------------------------------
# robustness: never crash the session
# --------------------------------------------------------------------------


def test_malformed_stdin_is_noop(tmp_path):
    """Garbage on stdin (not JSON) must not crash the session — exit 0, no output."""
    import os

    env = dict(os.environ)
    env["HOME"] = str(tmp_path / "home")
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path / "proj")
    proc = subprocess.run(
        [sys.executable, str(_HOOK)],
        input="this is not json {{{",
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


# --------------------------------------------------------------------------
# wiring: hook registered + commands shipped (no dangling references)
# --------------------------------------------------------------------------


def test_hook_is_registered_in_hooks_json():
    """The user-mem hook is wired under UserPromptSubmit in hooks/hooks.json and the script exists."""
    hooks_json = json.loads((_PROJECT_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    ups = hooks_json["hooks"]["UserPromptSubmit"]
    commands = [h["command"] for entry in ups for h in entry["hooks"]]
    assert any("on-prompt-submit-user-mem.py" in c for c in commands), "user-mem hook not registered"
    # The referenced script actually exists on disk (no dangling hook).
    assert _HOOK.is_file()


def test_three_commands_are_shipped():
    """All three slash commands exist with valid frontmatter (description present)."""
    cmd_dir = _PROJECT_ROOT / "commands"
    for name in ("to-user-mem", "search-user-mem", "share-user-mem"):
        path = cmd_dir / f"{name}.md"
        assert path.is_file(), f"missing command file: {name}.md"
        text = path.read_text(encoding="utf-8")
        assert text.startswith("---"), f"{name}.md missing frontmatter"
        fm = text.split("---", 2)[1]
        assert "description:" in fm, f"{name}.md missing description"
