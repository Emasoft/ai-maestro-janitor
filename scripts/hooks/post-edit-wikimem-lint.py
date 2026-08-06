#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""PostToolUse hook — lint a memory page the moment it is EDITED, not 15 minutes later.

THE GAP THIS CLOSES (owner directive 2026-08-06: *"I told you to enforce all rules
programmatically via the memgrep"*). The enforcement everyone believed existed did not:

  1. The write VERBS (`memgrep new-page` / `add-atom` / `add-lesson` / `edit`) validate what THEY
     write — but the standing rule explicitly permits the plain **Edit tool** as an alternative
     ("Edit pages ONLY via memgrep verbs or the Edit tool"). A page created clean by a verb and
     then amended by Edit is never seen by memgrep again.
  2. `memgrep validate` is NOT `memgrep lint`. The scope/link rules — including
     `link-downward-cross-scope` and the bidirectional LINK LAW — live ONLY in `lint`
     ("deterministic, FP-free note-integrity check (footnotes, the bidirectional link law,
     required fields)"). Running validate after an edit proves almost nothing.
  3. WORSE, measured 2026-08-06: `memgrep validate <path-that-does-not-exist>` prints `NONE` and
     exits 0. A `NONE` from validate is not evidence the file is clean — it is not even evidence
     the file was READ. Any workflow that gates on validate alone is gating on nothing.
  4. No hook ran lint. The only PostToolUse hook on memory writes
     (`post-edit-memory-correction.py`) nags about the correction protocol and never lints.

Net effect: a USER-scope page acquired a downward cross-scope wikilink via the Edit tool, passed
the author's own `validate`, and was caught ~15 minutes later by the heartbeat's `wikimem-syntax`
detector. The rule existed, the linter existed, and nothing connected them at write time.

This hook is that connection. It is deliberately a POST hook rather than a Pre-deny: the standing
rule ALLOWS the Edit tool, so denying it would fight the documented workflow. Instead the finding
lands in the same turn, while the author still has the context to fix it — which is the difference
between a correction and an archaeology exercise.

FAIL-OPEN, always: no memgrep, a timeout, garbage stdin, or a lint crash must never block a write.
A guard that breaks editing gets disabled, and a disabled guard protects nothing.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

ENABLED_ENV = "CLAUDE_PLUGIN_OPTION_WIKIMEM_LINT_ON_EDIT"
TIMEOUT_S = 8

# Same shape as post-edit-memory-correction: `*/memory/*.md`, excluding the private user-mem
# store, the MEMORY.md / memory-index.md index files, and the `.memgrep/` sidecar. Kept as its
# own copy rather than imported because that module is a HOOK (not a lib) and importing a hook
# from a hook makes both un-runnable standalone.
_MEMORY_PATH_RE = re.compile(r"(?:^|/)memory/.*\.md$")
_EXCLUDE_RE = re.compile(
    r"(?:^|/)user-mem/"
    r"|(?:^|/)\.memgrep/"
    r"|(?:^|/)MEMORY\.md$"
    r"|(?:^|/)memory-index\.md$"
)


def is_memory_page(file_path: str) -> bool:
    """True iff `file_path` is a wikimem PAGE whose edits the linter governs. PURE."""
    if not file_path:
        return False
    if _EXCLUDE_RE.search(file_path):
        return False
    return bool(_MEMORY_PATH_RE.search(file_path))


def error_findings(stdout: str) -> list[str]:
    """The ERROR-level finding lines in `memgrep lint` output. PURE.

    ERROR only, on purpose. WARN/INFO are real but often pre-existing and corpus-wide (the
    `link-one-sided` cluster is 30+ findings nobody's current edit introduced); surfacing those on
    every edit would train the author to ignore the hook, and an ignored hook is a disabled one.
    ERROR means "memgrep can no longer parse or resolve this" — recall-invisible, i.e. the note
    effectively does not exist.
    """
    return [ln for ln in stdout.splitlines() if ln.startswith("ERROR ")]


def gather_file_path(tool_input: dict) -> str:
    """The path a Edit/Write/MultiEdit payload targets ("" when absent)."""
    for key in ("file_path", "notebook_path", "path"):
        val = tool_input.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def find_memgrep() -> str | None:
    """Resolve the memgrep binary. Delegates to the shared resolver, with an inline fallback so
    the hook still works if that lib moves (a hook must not die on an import)."""
    try:
        import user_mem_lib  # noqa: PLC0415

        return user_mem_lib.find_memgrep()
    except Exception:  # noqa: BLE001
        import shutil  # noqa: PLC0415

        found = shutil.which("memgrep")
        if found:
            return found
        cargo = Path.home() / ".cargo" / "bin" / "memgrep"
        return str(cargo) if cargo.exists() else None


def main() -> int:
    if os.environ.get(ENABLED_ENV, "1").strip().lower() in ("0", "false", "no", "off"):
        return 0
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if data.get("tool_name", "") not in ("Edit", "Write", "MultiEdit"):
        return 0

    path = gather_file_path(data.get("tool_input") or {})
    if not is_memory_page(path):
        return 0  # fast path: a non-memory edit costs one regex
    if not Path(path).is_file():
        return 0  # the write may have been denied, or the path is a rename target

    binary = find_memgrep()
    if binary is None:
        return 0
    try:
        proc = subprocess.run(  # noqa: S603 - resolved binary + one path, no shell
            [binary, "lint", path],
            capture_output=True, text=True, timeout=TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return 0  # fail-open: a lint that cannot run must never block a write

    errors = error_findings(proc.stdout or "")
    if not errors:
        return 0

    # Named findings, not a "run the linter" nudge: the author is mid-turn with the context
    # loaded, and a nudge that makes them re-derive what the linter already computed is how a
    # guard becomes noise. Cap the list so a mass-edit cannot flood the turn.
    shown = errors[:5]
    more = f"\n  … and {len(errors) - len(shown)} more" if len(errors) > len(shown) else ""
    print(
        f"[wikimem-lint] `{path}` has {len(errors)} ERROR-level finding(s) — the page is "
        f"recall-INVISIBLE or ambiguous to memgrep until fixed. Fix them NOW, in this turn, "
        f"while you still have the context:\n  " + "\n  ".join(shown) + more +
        "\n  NOTE: `memgrep validate` does NOT catch these (it reports NONE even for a path that "
        "does not exist) — only `memgrep lint` does.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
