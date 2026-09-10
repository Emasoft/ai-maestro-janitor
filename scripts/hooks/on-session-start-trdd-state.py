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

- `source == "compact"` + a FRESH `precompact-handoff.md` (the common case — the
  PreCompact hook wrote it seconds earlier): inject a one-line warning + a pointer
  to the handoff + a one-line-per-TRDD digest. The handoff ALREADY carries these
  TRDDs' STATE blocks verbatim (plus git truth + verbatim recent turns) and the
  resume loop steers the next turn to read it — injecting the same blocks here
  DOUBLED the post-compact context (35.3 KB measured, TRDD-498LEWZ4).
- `source == "compact"` with NO fresh handoff (the janitor PreCompact hook is
  disabled, failed, or a foreign compaction path): inject each in-progress TRDD's
  FULL `## STATE` block (capped), prefixed as AUTHORITATIVE and SUPERSEDING any
  conflicting compaction-summary claim — failures fall toward MORE grounding.
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
import time
from pathlib import Path

MAX_TRDDS = 4              # cap how many in-progress TRDDs we surface
MAX_STATE_LINES = 140      # cap injected STATE lines per TRDD so context stays lean
_FRONT = 4000              # bytes of head to scan for frontmatter fields

# The PreCompact hook (pre-compact-handoff.py) writes this file seconds before a
# SessionStart:compact fires. When it is FRESH, it is THIS compaction's handoff and
# already carries the in-flight TRDDs' STATE blocks verbatim — so this hook injects a
# pointer + digest instead of a duplicate copy (TRDD-498LEWZ4). A file older than the
# window belongs to a PREVIOUS compaction: pointing the model at it would re-ground on
# outdated truth, so staleness falls back to the full STATE injection.
_HANDOFF_RELPATH = Path(".janitor") / "state" / "precompact-handoff.md"
_HANDOFF_FRESH_S = 900

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


def _column(text_head: str) -> str | None:
    m = re.search(r"^column:\s*(\S+)\s*$", text_head, re.MULTILINE)
    return m.group(1) if m else None


# TRDD v2 columns that mean "actively being worked" — the WORK group of the kanban
# (~/.claude/rules/trdd-design-tasks.md). v1's `status: in-progress` maps onto these.
_ACTIVE_COLUMNS = frozenset({"dev", "testing", "ai_review", "human_review"})


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


def _preamble(*, after_compact: bool, inject_full: bool, n_trdds: int) -> str:
    """The injection's leading paragraph for the three modes (full / digest / list)."""
    if inject_full:
        return (
            "⚠️ [janitor-trdd] A context COMPACTION just occurred — the summary is "
            "lossy and may carry WRONG technical conclusions. The AUTHORITATIVE `## STATE` "
            "block(s) of this project's in-progress TRDD(s) are injected below; they SUPERSEDE "
            "any conflicting claim in the compaction summary. Read them before acting."
        )
    if after_compact:
        return (
            "⚠️ [janitor-trdd] A context COMPACTION just occurred — the summary is "
            "lossy and may carry WRONG technical conclusions. The authoritative "
            "re-grounding (git truth, the in-progress TRDD `## STATE` blocks VERBATIM, "
            "the verbatim recent turns) is `.janitor/state/precompact-handoff.md` — "
            "READ IT FIRST, before acting on any summary claim. In-progress TRDDs:"
        )
    return (
        f"[janitor-trdd] {n_trdds} in-progress TRDD(s) in this project. Before touching "
        "their work, read the `## STATE` block of each (a compaction summary is not a "
        "substitute). Files:"
    )


def _fresh_handoff(project_dir: Path) -> Path | None:
    """The precompact handoff written by THIS compaction, or None.

    Freshness (mtime within `_HANDOFF_FRESH_S`) is what ties the file to the
    compaction that just ended — the PreCompact hook writes it moments before this
    hook fires. Any doubt (missing, stale, unreadable) returns None so the caller
    falls back to full injection: failures fall toward MORE grounding, not less.
    """
    p = project_dir / _HANDOFF_RELPATH
    try:
        if p.is_file() and (time.time() - p.stat().st_mtime) <= _HANDOFF_FRESH_S:
            return p
    except OSError:
        pass
    return None


def _trdd_paths(project_dir: Path) -> list[Path]:
    """Every TRDD on the board, across BOTH design scopes (PROJECT + LOCAL).

    FAIL-OPEN by design: on ANY import failure, fall back to the plain PROJECT board rather
    than raising. This is a SessionStart hook, and a SessionStart hook that dies on import
    runs nothing while Claude Code stays silent about it — the failure that left this
    plugin's OTHER SessionStart hook dead for three weeks. The board is a nicety; not
    crashing the session start is not.
    """
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
    if plugin_root:
        try:
            scripts = Path(plugin_root) / "scripts"
            # BOTH entries: `from lib import …` needs scripts/ on the path, and a lib module's
            # bare sibling import needs scripts/lib/ on it. Omitting the second is the exact
            # ModuleNotFoundError that killed on-session-start.py.
            for entry in (str(scripts), str(scripts / "lib")):
                if entry not in sys.path:
                    sys.path.insert(0, entry)
            from lib import trdd_common  # noqa: E402 - local package, not PyPI

            return [p for _scope, p in trdd_common.trdd_files("tasks", str(project_dir))]
        except Exception:  # noqa: BLE001 -- degrade to the project board; never break session start
            pass
    tasks_dir = project_dir / "design" / "tasks"
    if not tasks_dir.is_dir():
        return []
    return sorted(tasks_dir.glob("TRDD-*.md"))


def _in_progress(trdds: list[Path]) -> list[Path]:
    out: list[Path] = []
    for p in trdds:
        try:
            head = p.read_text(encoding="utf-8", errors="replace")[:_FRONT]
        except OSError:
            continue
        # v2 first (`column:` WORK group), v1 fallback (`status: in-progress`) — the
        # v1-only gate matched ZERO modern TRDDs, leaving the post-compaction turn
        # without the STATE block this hook exists to inject (review wf_6aee2965).
        if _column(head) in _ACTIVE_COLUMNS or _status(head) == "in-progress":
            out.append(p)
    return out


def _display(p: Path, project_dir: Path) -> str:
    """How to NAME a TRDD to the agent so it can actually open it.

    A PROJECT TRDD shows repo-relative (`design/tasks/X.md`). A LOCAL TRDD lives OUTSIDE
    the repo, so printing it repo-relative would name a file that does not exist — the
    agent would Read it, get nothing, and conclude the TRDD was lost. Print its real path
    (HOME collapsed to `~` for readability; still openable verbatim).
    """
    try:
        return str(p.relative_to(project_dir))
    except ValueError:
        try:
            return f"~/{p.relative_to(Path.home())}"
        except ValueError:
            return str(p)


def main() -> int:
    project_dir, source = _read_input()

    trdds = _in_progress(_trdd_paths(project_dir))[:MAX_TRDDS]
    if not trdds:
        return 0

    after_compact = source == "compact"
    # Inject full STATE blocks ONLY when there is no fresh handoff to point at —
    # the handoff already carries them verbatim, and one copy in context is enough.
    inject_full = after_compact and _fresh_handoff(project_dir) is None

    parts: list[str] = [
        _preamble(after_compact=after_compact, inject_full=inject_full, n_trdds=len(trdds))
    ]

    for p in trdds:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        title = _title(text[:_FRONT], p.name)
        shown = _display(p, project_dir)
        if inject_full:
            block = _state_block(text)
            if block:
                parts.append(f"\n--- {shown} — {title} ---\n{block}")
            else:
                parts.append(
                    f"\n--- {shown} — {title} "
                    "(no ## STATE block — read the file top-to-bottom) ---"
                )
        else:
            # Digest line — shared by the post-compact pointer mode AND the
            # startup/resume list: path + title + whether a STATE block exists.
            tag = "has ## STATE block" if _state_block(text) else "NO ## STATE block — read top-to-bottom"
            parts.append(f"  • {shown} — {title} ({tag})")

    # Stdout from a SessionStart hook becomes additional context for the first turn.
    print("\n".join(parts))
    return 0


if __name__ == "__main__":
    # Bare main() (returns 0 on every path) — matches the sibling hooks' pattern
    # so CPV's module-scope sys.exit detector stays quiet.
    main()
