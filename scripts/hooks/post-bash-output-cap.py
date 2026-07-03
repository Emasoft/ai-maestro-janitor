#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""PostToolUse hook — cap Bash tool output to bound the model's context (TRDD-ZNN0UK5K, S9).

WHY: unbounded Bash output (a full ``pytest`` log, a ``git diff``, a directory dump) floods the
model's context and inflates per-turn token cost — every line rides forward in the transcript
and is re-charged on every later turn. This hook replaces an oversized Bash result with a
HEAD+TAIL excerpt via CC's PostToolUse ``updatedToolOutput`` contract (the same mechanism the
janitor's ``post-mcp-response-sanitizer`` uses to replace ``mcp__*`` output). HEAD+TAIL — not a
plain head cut — because the TAIL is where ``pytest`` summaries and exit/error lines print; a
naive head cut would blind the agent to the very outcome it ran the command for.

Design invariants:
  * OPT-IN — it never surprises another janitor user (a global 500-char cap on every Bash call
    would be hostile). Active only when ``CLAUDE_PLUGIN_OPTION_BASH_OUTPUT_CAP_ENABLED`` is
    truthy OR the per-project sentinel ``<project>/.janitor/state/bash-output-cap`` exists — the
    sentinel is read at hook RUNTIME, so a session enables the cap WITHOUT a restart.
  * Cap is ``CLAUDE_PLUGIN_OPTION_BASH_OUTPUT_CAP_CHARS`` (default 500); ``cap <= 0`` disables.
  * FAIL-OPEN — ANY error → emit nothing → the original output is shown unchanged. A truncation
    hook must never be able to break a Bash call.
  * Rewrites ONLY when the output actually EXCEEDS the cap; short output passes through with zero
    overhead and no rewrite.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_DEFAULT_CAP = 500
# The middle marker names how much was hidden and nudges toward redirect-to-file for the full
# text. Its width bounds how much of the cap the head+tail split can use.
_MARKER_TMPL = (
    "\n…[janitor bash-cap: {hidden} of {total} chars hidden; "
    "redirect output to a file for the full text]…\n"
)


def cap_text(text: str, cap: int) -> str:
    """Return ``text`` capped to at most ``cap`` chars, preserving BOTH its head and its tail.

    Short-circuits when already within the cap. Otherwise keeps ~60% head + ~40% tail with a
    middle marker naming how much was hidden. The result is GUARANTEED ``<= cap``: the tail is
    trimmed if the real marker overflows, and as a last resort (a marker wider than the whole
    cap) the text is hard head-cut to ``cap``."""
    if cap <= 0 or len(text) <= cap:
        return text
    total = len(text)

    def build(head_len: int, tail_len: int) -> str:
        hidden = total - head_len - tail_len
        marker = _MARKER_TMPL.format(hidden=hidden, total=total)
        return text[:head_len] + marker + (text[-tail_len:] if tail_len > 0 else "")

    # Reserve for the WIDEST possible marker (hidden==total → most digits); the real marker can
    # only be shorter, so `out` stays within the cap by construction.
    marker_reserve = len(_MARKER_TMPL.format(hidden=total, total=total))
    budget = cap - marker_reserve
    if budget <= 0:
        return text[:cap]  # cap narrower than the marker itself → hard head-cut
    head_len = (budget * 6) // 10
    tail_len = budget - head_len
    out = build(head_len, tail_len)
    # Defensive: trim the tail if any rounding left `out` a hair over the cap.
    while len(out) > cap and tail_len > 0:
        tail_len -= 1
        out = build(head_len, tail_len)
    return out if len(out) <= cap else text[:cap]


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _cap_enabled(project_dir: Path) -> bool:
    if _truthy(os.environ.get("CLAUDE_PLUGIN_OPTION_BASH_OUTPUT_CAP_ENABLED")):
        return True
    # Runtime-read sentinel → a session can enable the cap without a plugin-config restart.
    return (project_dir / ".janitor" / "state" / "bash-output-cap").exists()


def _cap_chars() -> int:
    raw = os.environ.get("CLAUDE_PLUGIN_OPTION_BASH_OUTPUT_CAP_CHARS")
    if raw is None or not raw.strip():
        return _DEFAULT_CAP
    try:
        return int(raw.strip())
    except ValueError:
        return _DEFAULT_CAP


def _extract_output(tool_response: object) -> str:
    """Best-effort visible text of a Bash ``tool_response`` — a dict with stdout/stderr, a plain
    string, or a list of content blocks."""
    if isinstance(tool_response, str):
        return tool_response
    if isinstance(tool_response, dict):
        parts = [
            p
            for p in (tool_response.get("stdout"), tool_response.get("stderr"))
            if isinstance(p, str) and p
        ]
        if parts:
            return "\n".join(parts)
        val = tool_response.get("output") or tool_response.get("content")
        if isinstance(val, str):
            return val
        if isinstance(val, list):
            return "".join(b.get("text", "") for b in val if isinstance(b, dict))
        return ""
    if isinstance(tool_response, list):
        return "".join(b.get("text", "") for b in tool_response if isinstance(b, dict))
    return ""


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(data, dict) or data.get("tool_name") != "Bash":
        return 0
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    if not _cap_enabled(project_dir):
        return 0
    cap = _cap_chars()
    if cap <= 0:
        return 0
    text = _extract_output(data.get("tool_response"))
    if not text or len(text) <= cap:
        return 0
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "updatedToolOutput": cap_text(text, cap),
        }
    }
    json.dump(out, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
