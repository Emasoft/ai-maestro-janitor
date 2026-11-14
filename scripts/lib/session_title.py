"""Session names for sessions the janitor cleared into (issue #357).

WHY THIS EXISTS. Claude Code titles an untitled session from its first prompt. A session born
from the janitor's `/clear` has the `/clear` command record as that prompt, so it is named
"/clear clear", and every later clear copies the title forward. A UserPromptSubmit hook may
answer with `hookSpecificOutput.sessionTitle`; measured live on Claude Code 2.1.325 (a scratch
plugin printing that field): after `/clear` the first prompt's hook input had `session_title`
null, the NEXT prompt's input carried the name the hook returned, and /status showed it as
"Session name". `/clear` itself fires no UserPromptSubmit, so the first prompt is the earliest
place a name can be set.

Pure stdlib on purpose: `on-prompt-submit.py` calls this on cron fires too, and importing
`state` there costs ~50 ms per heartbeat (see that hook's docstring).
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

# Anything else (a leading "/", "@", ESC, newlines, quotes) never reaches the title bar.
_ALLOWED = re.compile(r"[^A-Za-z0-9 ._:#()-]")
_MAX_LEN = 60
# A handoff older than this does not say what THIS session is doing.
_HANDOFF_MAX_AGE_S = 60 * 60
_FALLBACK_NAME = "session"
# How much of a transcript head is scanned for the first user prompt.
_HEAD_BYTES = 64 * 1024
_HEAD_LINES = 200
_SECTION_HEADING = "## in-flight cards"
# `- TRDD-<ID8> (`column`) — <title>`, as rendered by external_clear's handoff composer.
_CARD_RE = re.compile(r"^- TRDD-([A-Z0-9]{8}) \(`[^`]*`\) — (.+)$")


def needs_title(session_title: Any) -> bool:
    """True when the hook input carries no usable title: missing, blank, or a "/command" echo."""
    if not isinstance(session_title, str):
        return True
    stripped = session_title.strip()
    return not stripped or stripped.startswith("/")


def _record_text(record: dict[str, Any]) -> str:
    """The text of a transcript `user` record (a plain string or a list of text blocks)."""
    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and isinstance(b.get("text"), str))
    return ""


def born_from_clear(transcript_path: Any) -> bool:
    """True iff the first user prompt in the transcript head is the `/clear` command record.

    Reads at most the first 64 KB / 200 lines (a head scan, never the whole file). The
    `local-command-caveat` record Claude Code writes just before the command is skipped. A
    missing, unreadable or non-string path is False: no rename, never an exception.
    """
    if not isinstance(transcript_path, str) or not transcript_path:
        return False
    try:
        with open(transcript_path, "rb") as fh:
            head = fh.read(_HEAD_BYTES)
    except OSError:
        return False
    for raw in head.splitlines()[:_HEAD_LINES]:
        try:
            record = json.loads(raw)
        except ValueError:
            continue  # blank line, or the last line cut by the byte cap
        if not isinstance(record, dict) or record.get("type") != "user":
            continue
        text = _record_text(record)
        if "<local-command-caveat>" in text:
            continue
        return "<command-name>/clear</command-name>" in text
    return False


def sanitise(raw: str, *, fallback: str) -> str:
    """Collapse whitespace, keep only [A-Za-z0-9 ._:#()-], cap 60 chars at a word boundary.

    Never returns an empty string: `fallback` stands in when nothing survives.
    """
    text = re.sub(r"\s+", " ", raw)
    text = re.sub(r" +", " ", _ALLOWED.sub("", text)).strip()
    if len(text) > _MAX_LEN:
        cut = text[:_MAX_LEN]
        # A space right after the cut means `cut` already ends on a whole word.
        if text[_MAX_LEN] != " " and " " in cut:
            cut = cut.rsplit(" ", 1)[0]
        text = cut.rstrip()
    return text or fallback


def _project_dir(payload: dict[str, Any]) -> Path | None:
    """CLAUDE_PROJECT_DIR, else the payload's cwd; None when neither names a folder."""
    for raw in (os.environ.get("CLAUDE_PROJECT_DIR", ""), payload.get("cwd")):
        if isinstance(raw, str) and raw.strip() and Path(raw.strip()).name:
            return Path(raw.strip())
    return None


def _newest_fresh_handoff(root: Path, now: float) -> Path | None:
    """The newest `agent-handoff*.md` under root/.janitor/state written within the last hour."""
    state_dir = root / ".janitor" / "state"
    if not state_dir.is_dir():
        return None
    newest: tuple[float, Path] | None = None
    for entry in state_dir.iterdir():
        if entry.name.startswith("agent-handoff") and entry.name.endswith(".md"):
            mtime = entry.stat().st_mtime
            if newest is None or mtime > newest[0]:
                newest = (mtime, entry)
    if newest is None or now - newest[0] > _HANDOFF_MAX_AGE_S:
        return None
    return newest[1]


def _single_in_flight_card(handoff_text: str) -> tuple[str, str] | None:
    """(id8, title) when the in-flight section lists exactly one card, else None."""
    bullets: list[str] = []
    in_section = False
    for line in handoff_text.splitlines():
        if line.startswith("## "):
            in_section = line.strip().lower().startswith(_SECTION_HEADING)
        elif in_section and line.startswith("- "):
            bullets.append(line.rstrip())
    if len(bullets) != 1:
        return None
    match = _CARD_RE.match(bullets[0])
    return (match.group(1), match.group(2)) if match else None


def choose_title(payload: dict[str, Any], *, now: float | None = None) -> str | None:
    """The name to set, or None when the input already has a good title or no name can be built.

    Raises on I/O trouble (an unreadable handoff): the caller logs one line and emits nothing.
    """
    session_title = payload.get("session_title")
    if not needs_title(session_title):
        return None
    # WHY the transcript gate (issue #357): a brand-new session titles ITSELF from its first
    # prompt, so a null title is normal everywhere and must be left to Claude Code. Only a session
    # born from /clear gets the "/clear clear" echo (its first prompt is the /clear command
    # record), so a null/blank title is renamed only then. A title that already starts with "/" is
    # the poisoned echo itself and is always replaced.
    if not (isinstance(session_title, str) and session_title.strip()) and not born_from_clear(payload.get("transcript_path")):
        return None
    root = _project_dir(payload)
    if root is None:
        return None
    project = root.name
    base = sanitise(project, fallback=_FALLBACK_NAME)
    handoff = _newest_fresh_handoff(root, time.time() if now is None else now)
    if handoff is not None:
        card = _single_in_flight_card(handoff.read_text(encoding="utf-8"))
        if card is not None:
            return sanitise(f"{project} TRDD-{card[0]} {card[1]}", fallback=base)
    return base


def merge_session_title(output: dict[str, Any], title: str) -> dict[str, Any]:
    """Add `sessionTitle` to hook output in place, keeping whatever hookSpecificOutput holds."""
    hso = output.setdefault("hookSpecificOutput", {})
    hso.setdefault("hookEventName", "UserPromptSubmit")
    hso["sessionTitle"] = title
    return output
