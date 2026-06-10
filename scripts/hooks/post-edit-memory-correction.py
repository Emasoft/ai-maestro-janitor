#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""PostToolUse hook — memory correction-protocol advisory (TRDD-c77dae09, rank 5).

Fires AFTER an Edit / Write to a MEMORY PAGE and, when the edit looks like a
fact was REWRITTEN in place without demoting the old fact to a lesson, surfaces
a one-line advisory `additionalContext` reminding the agent of the 2-step
non-destructive correction protocol (clean the fact in place + record the WHY as
a `[^N]` lesson). It is a NUDGE, never a block — the edit has already happened.

The 2-step protocol (the spec, mirrored in the janitor-memory-write skill):
  1. Clean the wrong fact in place (the body is the current truth).
  2. Demote the ERROR to a numbered `## Notes and lessons learned` entry, linked
     from the corrected fact via a `[^N]` footnote — because the WHY is the point
     (a lesson without a WHY can't stop the next repeat). RULE 0 / Bug-Autopsy:
     the fact is corrected, the error is NEVER deleted.

When this hook fires:
  * The edited path is a MEMORY PAGE — matches `*/memory/*.md`, EXCLUDING the
    private `user-mem/` store, the `MEMORY.md` index, and the `.memgrep/` sidecar.
  * The edit REPLACED body text rather than purely appending — detected from the
    Edit tool's `old_string`→`new_string` pair: a pure append/insert keeps the
    whole `old_string` verbatim inside `new_string`, so when `old_string` is
    NON-EMPTY and is NOT a substring of `new_string`, prior text was rewritten.
  * The edit adds NO new lesson — `new_string` introduces no `[^N]` reference, no
    `[^N]:` definition, and no `## Notes and lessons learned` header that
    `old_string` lacked.

Write is in the matcher so the hook SEES whole-file overwrites, but the
PostToolUse payload carries no prior file content for a Write — so "append vs
replace" is undeterminable and the hook stays SILENT on Write (a Write to a
memory page is most often a freshly-authored note, not a correction). The
replace-detection is therefore Edit-only by design (low false-positive).

Always exits 0. Fast path first: a non-memory path / non-Edit-Write tool /
garbage stdin returns instantly with no output. OPT-OUT via
CLAUDE_PLUGIN_OPTION_MEMORY_CORRECTION_ADVISORY=false (default ON — it is a
zero-cost advisory that never blocks).
"""

from __future__ import annotations

import json
import os
import re
import sys

# A memory-PAGE path: `.../memory/<note>.md`. The `(?:^|/)memory/` anchor makes
# `memory/` a full path segment (not a substring of e.g. `in-memory-cache.md`).
# The note must sit directly OR nested under a `memory/` segment.
_MEMORY_PATH_RE = re.compile(r"(?:^|/)memory/(?:[^/]+/)*[^/]+\.md$")

# Excluded from the memory-page match (privacy + non-note files):
#   - any path through the private `user-mem/` store (agent-invisible),
#   - the `MEMORY.md` human index and the generated `memory-index.md`,
#   - anything under the `.memgrep/` SQLite sidecar dir.
_EXCLUDE_RE = re.compile(
    r"(?:^|/)memory/(?:[^/]*/)*user-mem/"      # user-mem/ anywhere under memory/
    r"|(?:^|/)MEMORY\.md$"                       # the human index
    r"|(?:^|/)memory-index\.md$"                 # the generated index
    r"|(?:^|/)\.memgrep/"                        # the sidecar dir
)

# Lesson-machinery signals — their PRESENCE in new text that wasn't in the old
# means the agent DID add a lesson, so the nudge is suppressed.
_FOOTNOTE_REF_RE = re.compile(r"(?<!\\)\[\^\d+\]")          # a `[^N]` reference
_LESSONS_HEADER_RE = re.compile(
    r"^\s*#{2,}\s+notes\s+(?:and|&)\s+lessons\s+learned\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _is_truthy_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "")
    if not raw:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y", "t"}


def _is_memory_page(file_path: str) -> bool:
    """True iff `file_path` is a memory PAGE the correction protocol governs.

    Matches `*/memory/*.md` and excludes the private user-mem store, the
    MEMORY.md / memory-index.md index files, and the `.memgrep/` sidecar.
    """
    if not file_path:
        return False
    if _EXCLUDE_RE.search(file_path):
        return False
    return bool(_MEMORY_PATH_RE.search(file_path))


def _adds_lesson(old: str, new: str) -> bool:
    """True iff `new` introduces lesson machinery that `old` did not have.

    "Introduces" = the count of `[^N]` references went up, OR a lessons-section
    header now appears that wasn't in the replaced text. Either means the agent
    paired the fact-change with a lesson, so no nudge is warranted.
    """
    if len(_FOOTNOTE_REF_RE.findall(new)) > len(_FOOTNOTE_REF_RE.findall(old)):
        return True
    new_has_header = bool(_LESSONS_HEADER_RE.search(new))
    old_has_header = bool(_LESSONS_HEADER_RE.search(old))
    return new_has_header and not old_has_header


def _is_replacement(old: str, new: str) -> bool:
    """True iff the edit REWROTE prior text rather than purely appending/inserting.

    A pure append or insert keeps the entire replaced span verbatim — i.e.
    `old` appears unchanged as a substring of `new`. When `old` is non-empty and
    is NOT a substring of `new`, body text was rewritten (the correction-shaped
    mutation). An empty `old` (a pure insertion at a point) is never a
    replacement.
    """
    old = old.strip("\n")
    if not old.strip():
        return False
    return old not in new


def _correction_nudge_needed(tool: str, tool_input: dict) -> bool:
    """Decide whether to surface the correction-protocol advisory.

    Edit-only by design: a Write carries no prior content in the PostToolUse
    payload, so append-vs-replace is undeterminable and we stay silent on it.
    """
    if tool != "Edit":
        return False
    old = str(tool_input.get("old_string") or "")
    new = str(tool_input.get("new_string") or "")
    if not _is_replacement(old, new):
        return False           # pure append/insert — not a fact rewrite
    if _adds_lesson(old, new):
        return False           # the rewrite DID add a lesson — protocol followed
    return True


def _gather_file_path(tool_input: dict) -> str:
    for key in ("file_path", "filePath", "path", "notebook_path"):
        v = tool_input.get(key)
        if isinstance(v, str) and v:
            return v
    return ""


def main() -> int:
    if not _is_truthy_env("CLAUDE_PLUGIN_OPTION_MEMORY_CORRECTION_ADVISORY", True):
        return 0
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # garbage stdin → silent no-op

    tool = data.get("tool_name", "")
    if tool not in ("Edit", "Write"):
        return 0
    tool_input = data.get("tool_input") or {}

    file_path = _gather_file_path(tool_input)
    # FAST PATH: a non-memory path exits before any payload analysis.
    if not _is_memory_page(file_path):
        return 0

    if not _correction_nudge_needed(tool, tool_input):
        return 0  # append, or a rewrite that already added a lesson → silent

    msg = (
        f"[memory-correction] memory page `{file_path}` was edited (a fact "
        f"rewritten in place) without adding a lesson. If this corrected a "
        f"WRONG fact, apply the 2-step non-destructive protocol: (1) keep the "
        f"corrected fact clean in the body, and (2) demote the error to a "
        f"numbered `## Notes and lessons learned` entry linked via a `[^N]` "
        f"footnote, recording the WHY (the root cause — a lesson without a WHY "
        f"can't stop the next repeat). RULE 0 / Bug-Autopsy: correct the fact, "
        f"never delete the error."
    )
    # Advisory only — surface a user-visible stderr line AND additionalContext so
    # the model sees the nudge on its next turn. NEVER block (the edit is done).
    print(msg, file=sys.stderr)
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": msg,
        },
    }
    json.dump(out, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
