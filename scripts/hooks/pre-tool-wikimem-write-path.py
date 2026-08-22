#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""PreToolUse: memgrep is the ONLY write path to a wikimem page (TRDD-VOWAUVE5, USER #6).

USER ruling 2026-08-22: *"enforce the use of memgrep when writing/updating/editing/migrate/
create new pages/create new atoms. Everything must pass via memgrep. so memgrep can lint and
ensure always 100% compliance with the wikimem specs."*

This REVERSES a documented decision, so the reversal is stated where the old one lived:
`post-edit-wikimem-lint.py` is deliberately a POST hook and says *"the standing rule explicitly
permits the plain Edit tool as an alternative"* and *"denying it would fight the documented
workflow."* That was true under the old rule. The rule changed; that header is updated in the
same commit, because a codebase arguing with itself is worse than either answer.

WHY a deny and not another nudge: the corpus's structural guarantees come from memgrep
SYNTHESISING the element (`main.rs:475` — "the parser's own crate SYNTHESISES the element so a
malformed atom/page/lesson is impossible"). A hand-written page bypasses that by construction,
so no amount of after-the-fact linting restores the guarantee — it can only report the damage.

FAIL-OPEN, deliberately. Every uncertainty — unreadable stdin, a path we cannot classify, an
exception anywhere — allows the write. A memory hook that blocks writes when confused would
make the corpus UNEDITABLE at exactly the moment someone is trying to repair it, and an
un-writable memory is a worse failure than an unlinted page.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ENABLED_ENV = "CLAUDE_PLUGIN_OPTION_WIKIMEM_WRITE_PATH_ENFORCED"

# Same shape as post-edit-wikimem-lint / post-edit-memory-correction: `*/memory/*.md`, minus the
# private user-mem store, the MEMORY.md / memory-index.md index files, and the `.memgrep/`
# sidecar. Copied rather than imported for the reason that file states: importing a HOOK from a
# hook makes both un-runnable standalone.
_MEMORY_PATH_RE = re.compile(r"(?:^|/)memory/.*\.md$")
_EXCLUDE_RE = re.compile(
    r"(?:^|/)user-mem/"
    r"|(?:^|/)\.memgrep/"
    r"|(?:^|/)MEMORY\.md$"
    r"|(?:^|/)memory-index\.md$"
    # The transaction core's own staging + journal. memgrep writes these THROUGH the Edit path
    # while a chore is in flight; denying them would deadlock the very tool this hook exists to
    # funnel writes into.
    r"|(?:^|/)\.maint-staging/"
)

_REASON = """This is a wikimem memory page, and memgrep is the only write path to one
(USER ruling 2026-08-22, TRDD-VOWAUVE5).

Use the write verb that matches the intent — each SYNTHESISES the element, so a malformed
atom/page/lesson is impossible by construction, and each validates + reindexes as it writes:

  memgrep new-page    <path>  --title ... --description ...   # a new page
  memgrep add-atom    --page <path> --keywords ...            # a new fact
  memgrep add-lesson  --page <path> --atom <id> --keywords ...# a [^N] lesson
  memgrep edit        --page <path> ...                       # CAS replace of existing text
  memgrep migrate     --page <path> ...                       # move a body verbatim

Correct a WRONG fact with `add-lesson --supersedes` (same atom id) — never by overwriting it.
Then: `memgrep validate <page> && memgrep lint <page>`.

Editing the file directly bypasses the parser, the CAS staleness guard, and the scope lock, so
the corpus loses the guarantees the memory system is built on. Nothing here forbids the CONTENT
you were about to write — only the path it takes to get in."""


def _enabled() -> bool:
    v = os.environ.get(ENABLED_ENV)
    return True if v is None else v.strip().lower() not in {"0", "false", "no", "off"}


def is_memory_page(file_path: str) -> bool:
    """True iff `file_path` is a wikimem page this hook governs."""
    if not file_path:
        return False
    p = str(Path(file_path)).replace(os.sep, "/")
    if not p.endswith(".md"):
        return False
    return bool(_MEMORY_PATH_RE.search(p)) and not _EXCLUDE_RE.search(p)


def main() -> int:
    if not _enabled():
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 -- unreadable stdin must never block a write
        return 0
    try:
        tool = payload.get("tool_name") or ""
        if tool not in {"Edit", "Write", "MultiEdit", "NotebookEdit"}:
            return 0
        ti = payload.get("tool_input") or {}
        target = ti.get("file_path") or ti.get("notebook_path") or ""
        if not is_memory_page(str(target)):
            return 0
        json.dump(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": _REASON,
                },
            },
            sys.stdout,
        )
    except Exception:  # noqa: BLE001 -- see the FAIL-OPEN note in the module docstring
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
