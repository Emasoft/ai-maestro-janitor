#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""SessionStart hook — actively surface in-progress TRDD STATE blocks on resume.

Enforcement counterpart to `~/.claude/rules/trdd-design-tasks.md`. A RULE is
PASSIVE — it is text the model can ignore, and did: a compacted session re-derived
a plan two durable artifacts already contained, because nothing FORCED a read of
the TRDD's authoritative `## STATE` head block. This HOOK is ACTIVE enforcement.

On every SessionStart it scans `<project>/design/tasks/` for `status: in-progress`
TRDDs and injects a reminder into the first turn's context:

- `source == "compact"` (the dangerous moment — a lossy summary just replaced the
  real plan): inject each in-progress TRDD's FULL `## STATE` block (capped),
  prefixed as AUTHORITATIVE and SUPERSEDING any conflicting compaction-summary
  claim. The truth is back in context before the first post-compact turn.
- any other source (startup / resume / clear): list the in-progress TRDDs + paths
  and direct the model to read their STATE blocks before touching that work.

Silent when the project has no in-progress TRDD (zero noise for projects without
active design work). Best-effort and fully isolated: ANY failure prints nothing
and exits 0 — a reminder hook must never disrupt session start.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

MAX_TRDDS = 4              # cap how many in-progress TRDDs we surface
MAX_STATE_LINES = 140      # cap injected STATE lines per TRDD so context stays lean
_FRONT = 4000              # bytes of head to scan for frontmatter fields

# Matches the STATE head heading: "## ⏵ STATE …" or "## STATE …" (⏵ = U+23F5).
_STATE_HEADING = re.compile(r"^##\s+(?:⏵\s*)?STATE\b")


def _read_input() -> tuple[Path, str]:
    """Return (project_dir, source) from the hook's stdin JSON, with fallbacks."""
    cwd, source = "", ""
    try:
        # A TTY would block on read(); only consume stdin when piped (the real
        # hook path always pipes JSON + EOF, so this never hangs in production).
        if not sys.stdin.isatty():
            raw = sys.stdin.read()
            if raw.strip():
                data = json.loads(raw)
                cwd = str(data.get("cwd", "")).strip()
                source = str(data.get("source", "")).strip()
    except Exception:
        pass
    if not cwd:
        cwd = os.environ.get("CLAUDE_PROJECT_DIR", "").strip() or os.getcwd()
    return Path(cwd), source


def _status(text_head: str) -> str | None:
    m = re.search(r"^status:\s*(\S+)\s*$", text_head, re.MULTILINE)
    return m.group(1) if m else None


def _title(text_head: str, fallback: str) -> str:
    m = re.search(r"^title:\s*(.+)$", text_head, re.MULTILINE)
    return m.group(1).strip() if m else fallback


def _state_block(text: str) -> str | None:
    """Extract the `## STATE` head section (until the next `## ` heading)."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if _STATE_HEADING.match(ln)), None)
    if start is None:
        return None
    end = next((j for j in range(start + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
    block = lines[start:end]
    if len(block) > MAX_STATE_LINES:
        block = block[:MAX_STATE_LINES] + ["… (STATE block truncated — read the full TRDD file)"]
    return "\n".join(block).strip()


def _in_progress(tasks_dir: Path) -> list[Path]:
    out: list[Path] = []
    for p in sorted(tasks_dir.glob("TRDD-*.md")):
        try:
            head = p.read_text(encoding="utf-8", errors="replace")[:_FRONT]
        except OSError:
            continue
        if _status(head) == "in-progress":
            out.append(p)
    return out


def main() -> int:
    project_dir, source = _read_input()
    tasks_dir = project_dir / "design" / "tasks"
    if not tasks_dir.is_dir():
        return 0

    trdds = _in_progress(tasks_dir)[:MAX_TRDDS]
    if not trdds:
        return 0

    after_compact = source == "compact"
    parts: list[str] = []
    if after_compact:
        parts.append(
            "⚠️ [janitor-trdd] A context COMPACTION just occurred — the summary is "
            "lossy and may carry WRONG technical conclusions. The AUTHORITATIVE `## STATE` "
            "block(s) of this project's in-progress TRDD(s) are injected below; they SUPERSEDE "
            "any conflicting claim in the compaction summary. Read them before acting."
        )
    else:
        parts.append(
            f"[janitor-trdd] {len(trdds)} in-progress TRDD(s) in this project. Before touching "
            "their work, read the `## STATE` block of each (a compaction summary is not a "
            "substitute). Files:"
        )

    for p in trdds:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        title = _title(text[:_FRONT], p.name)
        if after_compact:
            block = _state_block(text)
            if block:
                parts.append(f"\n--- design/tasks/{p.name} — {title} ---\n{block}")
            else:
                parts.append(
                    f"\n--- design/tasks/{p.name} — {title} "
                    "(no ## STATE block — read the file top-to-bottom) ---"
                )
        else:
            tag = "has ## STATE block" if _state_block(text) else "NO ## STATE block — read top-to-bottom"
            parts.append(f"  • design/tasks/{p.name} — {title} ({tag})")

    # Stdout from a SessionStart hook becomes additional context for the first turn.
    print("\n".join(parts))
    return 0


if __name__ == "__main__":
    # Bare main() (returns 0 on every path) — matches the sibling hooks' pattern
    # so CPV's module-scope sys.exit detector stays quiet.
    main()
