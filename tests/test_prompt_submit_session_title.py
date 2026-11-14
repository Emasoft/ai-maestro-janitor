"""Issue #357: on-prompt-submit.py names a session born from the janitor's /clear.

Claude Code titles an untitled session from its first prompt, so a session the janitor
cleared into is called "/clear clear" and every later clear copies that forward. The hook
answers a missing or "/"-prefixed `session_title` with `hookSpecificOutput.sessionTitle`
(measured live on Claude Code 2.1.325: the next prompt then carries the name and /status
shows it). Every test feeds real hook-input JSON to the real script in a subprocess.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_HOOK = _ROOT / "scripts" / "hooks" / "on-prompt-submit.py"
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

_PROJECT = "myproj"
_HANDOFF = "agent-handoff-abcd1234-20261114_193032+0100-4242.md"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project folder named `myproj` with an empty janitor state dir, under an isolated tmp."""
    root = tmp_path / _PROJECT
    (root / ".janitor" / "state").mkdir(parents=True)
    (tmp_path / "home").mkdir()
    return root


def _run(project: Path, payload: dict[str, Any], *, project_env: bool = True) -> tuple[int, str]:
    """Run the real hook script on `payload` as stdin JSON; return (exit code, stdout)."""
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    env["HOME"] = str(project.parent / "home")
    if project_env:
        env["CLAUDE_PROJECT_DIR"] = str(project)
    done = subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=str(project),
        timeout=60,
        check=False,
    )
    return done.returncode, done.stdout


def _transcript(project: Path, kind: str) -> str:
    """Write a session transcript head (`clear`: born from /clear, `normal`: a fresh prompt)."""
    caveat = {
        "type": "user",
        "isMeta": True,
        "message": {"role": "user", "content": "<local-command-caveat>run directly, not for you</local-command-caveat>"},
    }
    clear = {
        "type": "user",
        "message": {
            "role": "user",
            "content": "<command-name>/clear</command-name>\n  <command-message>clear</command-message>\n  <command-args></command-args>",
        },
    }
    normal = {"type": "user", "message": {"role": "user", "content": "please fix the flaky test"}}
    noise = {"type": "attachment", "attachment": {"type": "hook_success", "content": "x" * 5000}}
    records = [{"type": "mode", "mode": "normal"}, noise, caveat, clear] if kind == "clear" else [noise, normal, clear]
    path = project.parent / f"{kind}.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return str(path)


def _title(project: Path, session_title: Any = None, *, transcript: str | None = "clear") -> str | None:
    """The `sessionTitle` the hook emitted for a prompt carrying `session_title`, else None."""
    payload: dict[str, Any] = {"prompt": "hello there", "session_title": session_title}
    if transcript is not None:
        payload["transcript_path"] = _transcript(project, transcript)
    rc, out = _run(project, payload)
    assert rc == 0
    if not out.strip():
        return None
    hso = json.loads(out)["hookSpecificOutput"]
    assert hso["hookEventName"] == "UserPromptSubmit"
    return str(hso["sessionTitle"])


def _handoff(project: Path, cards: list[tuple[str, str, str]], *, age_s: float = 0) -> Path:
    """Write a handoff listing `cards` (id8, column, title) under its in-flight section."""
    lines = ["# Handoff", "", "## NEXT ACTION (one step, runnable)", "", "do it", ""]
    lines += ["## In-flight cards (open work)", ""]
    lines += [f"- TRDD-{cid} (`{col}`) — {title}" for cid, col, title in cards]
    lines += ["", "## Other open cards", "", "- other open cards: AAAAAAAA, BBBBBBBB", ""]
    path = project / ".janitor" / "state" / _HANDOFF
    path.write_text("\n".join(lines), encoding="utf-8")
    when = time.time() - age_s
    os.utime(path, (when, when))
    return path


def test_null_session_title_gets_the_project_name(project: Path) -> None:
    """A null session_title (first prompt after /clear) is answered with the project folder name."""
    assert _title(project, None) == _PROJECT


def test_missing_session_title_key_gets_the_project_name(project: Path) -> None:
    """A payload with no session_title key at all is treated like a null title."""
    rc, out = _run(project, {"prompt": "hello there", "transcript_path": _transcript(project, "clear")})
    assert rc == 0
    assert json.loads(out)["hookSpecificOutput"]["sessionTitle"] == _PROJECT


def test_clear_clear_title_is_replaced(project: Path) -> None:
    """The poisoned "/clear clear" title is replaced whatever the transcript says, even with none."""
    assert _title(project, "/clear clear", transcript=None) == _PROJECT
    assert _title(project, "/clear clear", transcript="normal") == _PROJECT


def test_null_title_with_a_normal_first_prompt_is_left_to_claude_code(project: Path) -> None:
    """A fresh user session titles itself from its first prompt, so no sessionTitle is emitted."""
    assert _title(project, None, transcript="normal") is None
    assert _title(project, "  ", transcript="normal") is None


def test_null_title_without_a_transcript_path_emits_nothing(project: Path) -> None:
    """No transcript_path means the birth of the session is unknown, so nothing is renamed."""
    assert _title(project, None, transcript=None) is None


def test_null_title_with_a_missing_transcript_file_emits_nothing(project: Path) -> None:
    """A transcript_path that does not exist exits 0 with empty stdout and no log line."""
    payload = {"prompt": "hello there", "session_title": None, "transcript_path": str(project.parent / "gone.jsonl")}
    rc, out = _run(project, payload)
    assert rc == 0
    assert out == ""
    assert not (project / ".janitor" / "logs" / "prompt-submit.log").exists()


def test_meaningful_title_emits_nothing(project: Path) -> None:
    """A real title is left alone: no sessionTitle key and no stdout at all."""
    rc, out = _run(project, {"prompt": "hello there", "session_title": "my own name"})
    assert rc == 0
    assert out == ""


def test_one_in_flight_card_in_a_fresh_handoff_names_the_card(project: Path) -> None:
    """Exactly one in-flight card in a fresh handoff gives "<project> TRDD-<ID8> <title>"."""
    _handoff(project, [("A1B2C3D4", "dev", "Fix the thing")], age_s=120)
    assert _title(project, None) == f"{_PROJECT} TRDD-A1B2C3D4 Fix the thing"


def test_two_in_flight_cards_fall_back_to_the_project_name(project: Path) -> None:
    """Two in-flight cards are ambiguous, so the name is just the project."""
    _handoff(project, [("A1B2C3D4", "dev", "Fix the thing"), ("E5F6G7H8", "todo", "Other")])
    assert _title(project, None) == _PROJECT


def test_stale_handoff_falls_back_to_the_project_name(project: Path) -> None:
    """A handoff older than 60 minutes is ignored even with a single card."""
    _handoff(project, [("A1B2C3D4", "dev", "Fix the thing")], age_s=61 * 60)
    assert _title(project, None) == _PROJECT


def test_handoff_just_inside_the_hour_is_used(project: Path) -> None:
    """A handoff 59 minutes old still counts as fresh."""
    _handoff(project, [("A1B2C3D4", "dev", "Fix the thing")], age_s=59 * 60)
    assert _title(project, None) == f"{_PROJECT} TRDD-A1B2C3D4 Fix the thing"


def test_card_title_with_hostile_characters_is_sanitised_end_to_end(project: Path) -> None:
    """ESC, "@" and a very long card title never reach the emitted name."""
    _handoff(project, [("A1B2C3D4", "dev", "\x1b[31mping @owner now " + "word " * 40)])
    name = _title(project, None)
    assert name is not None
    assert "\x1b" not in name and "@" not in name and len(name) <= 60
    assert name.startswith(f"{_PROJECT} TRDD-A1B2C3D4 ")


def test_cron_marker_prompt_still_gets_the_title(project: Path) -> None:
    """The first prompt after the janitor's /clear is a [janitor-…] cue; it must be named too."""
    payload = {"prompt": "[janitor-resume]\nresume", "session_title": None, "transcript_path": _transcript(project, "clear")}
    rc, out = _run(project, payload)
    assert rc == 0
    assert json.loads(out)["hookSpecificOutput"]["sessionTitle"] == _PROJECT


def test_no_project_env_falls_back_to_the_cwd_basename(project: Path) -> None:
    """Without CLAUDE_PROJECT_DIR the payload's cwd basename names the session."""
    payload = {"prompt": "hello", "session_title": None, "cwd": str(project), "transcript_path": _transcript(project, "clear")}
    rc, out = _run(project, payload, project_env=False)
    assert rc == 0
    assert json.loads(out)["hookSpecificOutput"]["sessionTitle"] == _PROJECT


def test_unreadable_handoff_changes_nothing_and_logs_one_line(project: Path) -> None:
    """A handoff that cannot be read leaves stdout empty, exits 0 and logs exactly one line."""
    (project / ".janitor" / "state" / _HANDOFF).mkdir()
    payload = {"prompt": "hello there", "session_title": None, "transcript_path": _transcript(project, "clear")}
    rc, out = _run(project, payload)
    assert rc == 0
    assert out == ""
    log = project / ".janitor" / "logs" / "prompt-submit.log"
    lines = [ln for ln in log.read_text().splitlines() if "session title" in ln]
    assert len(lines) == 1, lines


@pytest.mark.parametrize(
    ("raw", "want"),
    [
        ("/clear clear", "clear clear"),
        ("  /// lead slash", "lead slash"),
        ("a\nb\t c", "a b c"),
        ("ping @owner", "ping owner"),
        ("\x1b[31mred\x1b[0m", "31mred0m"),
        ("keep ._:#()- ok", "keep ._:#()- ok"),
        ("", "fallback"),
        ("@@@ \x1b", "fallback"),
        ("x" * 300, "x" * 60),
        ("word " * 100, " ".join(["word"] * 12)),
        ("aaa " + "b" * 70, "aaa"),
    ],
)
def test_sanitise_table(raw: str, want: str) -> None:
    """The sanitiser keeps only the allowed charset, collapses whitespace and caps 60 at a word."""
    import session_title  # noqa: PLC0415 -- lib dir is on sys.path above

    assert session_title.sanitise(raw, fallback="fallback") == want


def test_merge_keeps_existing_additional_context() -> None:
    """Adding the title to hook output that already has additionalContext keeps that context."""
    import session_title  # noqa: PLC0415 -- lib dir is on sys.path above

    existing = {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "keep me"}}
    merged = session_title.merge_session_title(existing, "myproj")
    assert merged["hookSpecificOutput"] == {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": "keep me",
        "sessionTitle": "myproj",
    }
    assert merged is existing
