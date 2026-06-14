#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""TRDD drift detector — Python port of trdd-drift.sh.

One-shot scan for stale active TRDDs — frontmatter `status:`
`not-started`/`in-progress` (v1) or a v2 `column:` in the
actively-in-flight set — that have not been touched for too long.
"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import state  # noqa: E402

# Matches both TRDD filename formats and captures a stable id used for the
# dedupe key + the short display ref:
#   * current (~/.claude/rules/trdd-design-tasks.md):
#       TRDD-<YYYYMMDD_HHMMSS±HHMM>-<uid-first-8>-<slug>.md  → capture the uid8
#   * legacy: TRDD-<full-UUID>-<slug>.md                     → capture the UUID
# The hex-length floor (8 for the new uid, 36 for the legacy UUID) prevents
# the collision the old too-permissive regex allowed (`TRDD-deadbeef.md`
# landing id="" and colliding on `drift@@bucket-N`). The two alternatives are
# mutually exclusive — a `_` in the timestamp can't appear in a UUID, and a
# UUID has no `_`, so neither branch can steal the other's filenames.
_TRDD_NAME_RE = re.compile(
    r"^TRDD-"
    r"(?:"
    r"\d{8}_\d{6}[+-]\d{4}-([0-9a-f]{8})"   # current: <timestamp>-<uid8>
    r"|([0-9a-f-]{36})"                      # legacy:  <full-uuid>
    r")"
    r"-.+\.md$"
)

# The canonical TRDD format (~/.claude/rules/trdd-design-tasks.md) puts the
# task state in YAML frontmatter — `status:` (v1) and/or `column:` (v2) —
# NOT a `**Status:**` markdown body line. We parse the frontmatter first and
# keep the legacy `**Status:**` body line as a fallback for pre-frontmatter
# TRDDs. All matches are anchored MULTILINE within the opening `---` block.
_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|$)", re.DOTALL)
_FM_STATUS_RE = re.compile(r"^status:[ \t]*(.+)$", re.MULTILINE)
_FM_COLUMN_RE = re.compile(r"^column:[ \t]*(.+)$", re.MULTILINE)
# Legacy `**Status:** ...` markdown body line (pre-frontmatter TRDDs only).
_LEGACY_STATUS_RE = re.compile(r"^\*\*Status:\*\*[ \t]*(.+)$", re.MULTILINE)

# Read only the head of the file — frontmatter lives at the very top, and a
# legacy `**Status:**` line sits just under the title. 4 KiB covers both
# without slurping a multi-thousand-line TRDD body.
_HEAD_BYTES = 4096

# v2 `column:` values that mean "actively in flight" (per the task spec).
# Used by both trdd-drift and trdd-reminder.
_ACTIVE_COLUMNS = frozenset(
    {"dev", "testing", "backburner", "todo", "dispatch", "ai_review", "human_review"}
)


def _norm_state(value: str) -> str:
    """Normalise a status/column token to lowercase kebab-case.

    Maps the legacy title-case body values (`In progress`, `Not started`)
    onto their frontmatter spellings (`in-progress`, `not-started`) by
    lowercasing and collapsing internal whitespace to a single hyphen, so a
    single membership set covers both formats.
    """
    return "-".join(value.strip().rstrip("\r").lower().split())


def _parse_trdd_state(path: Path) -> tuple[str, str]:
    """Return (status, column) for a TRDD, both normalised kebab-case or ''.

    Reads the YAML frontmatter `status:`/`column:` keys (the documented
    location), falling back to a legacy `**Status:**` body line when the
    frontmatter has no `status:`. Returns ('', '') on any read error.
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            head = f.read(_HEAD_BYTES)
    except (FileNotFoundError, OSError):
        return ("", "")

    status = ""
    column = ""
    fm = _FRONTMATTER_RE.match(head)
    if fm:
        block = fm.group(1)
        sm = _FM_STATUS_RE.search(block)
        if sm:
            status = _norm_state(sm.group(1))
        cm = _FM_COLUMN_RE.search(block)
        if cm:
            column = _norm_state(cm.group(1))

    # Legacy fallback only when the frontmatter carried no status: key.
    if not status:
        lm = _LEGACY_STATUS_RE.search(head)
        if lm:
            status = _norm_state(lm.group(1))

    return (status, column)


# Status values (v1 frontmatter / legacy body) that warrant a drift nudge.
_DRIFT_ACTIVE_STATUSES = frozenset({"not-started", "in-progress"})


def _last_touched_epoch(path: Path, project_root: Path) -> int:
    """Prefer git last-commit timestamp, fall back to mtime for uncommitted files.

    Bounded by a 5s timeout — `git log -1` is normally instant but a
    corrupted refs pack would otherwise hang the whole heartbeat.
    """
    proc = state.run_subprocess(
        ["git", "-C", str(project_root), "log", "-1", "--format=%ct", "--", str(path)],
        timeout=5,
        detector_name="trdd-drift",
    )
    if proc is not None and proc.returncode == 0:
        out = proc.stdout.strip()
        if out.isdigit():
            return int(out)
    return state.file_mtime(path)


def main() -> int:
    state.init_state()
    # Context gate (TRDD-db169d9e R1): TRDD enforcement is an ai-maestro/Emasoft
    # framework convention. The janitor runs at USER scope in EVERY project, so
    # stay silent in projects that aren't ai-maestro-plugins members. (Override
    # with JANITOR_FORCE_AI_MAESTRO=1 to use TRDDs in a non-ai-maestro project.)
    if not state.project_is_ai_maestro():
        return 0

    stale_days = state.coerce_int(os.environ.get("CLAUDE_PLUGIN_OPTION_TRDD_STALENESS_DAYS"), 14)
    seen = state.state_dir() / "trdd-drift-seen.txt"

    root = state.project_root()
    trdd_subpath = os.environ.get("CLAUDE_PLUGIN_OPTION_TRDD_PATH", "design/tasks").rstrip("/")
    trdd_dir = root / trdd_subpath

    # Containment check: a misconfigured CLAUDE_PLUGIN_OPTION_TRDD_PATH
    # (absolute system path, parent-escape sequence, or a symlink that
    # escapes the project root) must NOT cause the detector to scan
    # outside the project. Resolve both paths (resolves symlinks too)
    # and require the TRDD dir to live under root. The well-formed
    # default design/tasks always passes; only typo'd values fail.
    try:
        resolved_trdd = trdd_dir.resolve()
        resolved_root = root.resolve()
        resolved_trdd.relative_to(resolved_root)
    except (ValueError, OSError):
        state.log_line(
            "trdd-drift",
            f"TRDD path {trdd_subpath!r} resolves outside project root — refusing to scan",
        )
        return 0

    if not trdd_dir.is_dir():
        state.log_line("trdd-drift", f"TRDD dir {trdd_dir} not present — skipping")
        return 0

    now = int(time.time())

    for f in sorted(trdd_dir.glob("TRDD-*.md")):
        status, column = _parse_trdd_state(f)
        # A TRDD is drift-eligible when its v1 status is not-started/in-progress
        # OR its v2 column is one of the actively-in-flight columns. The column
        # set is broader on purpose — a `backburner`/`todo` TRDD that hasn't
        # moved in weeks is exactly the staleness we want to surface.
        if status not in _DRIFT_ACTIVE_STATUSES and column not in _ACTIVE_COLUMNS:
            continue
        # Prefer the explicit status for the drift line; fall back to the
        # column label when only v2 frontmatter is present.
        active_label = status or column

        touched = _last_touched_epoch(f, root)
        if touched == 0:
            continue

        age_days = (now - touched) // 86400
        if age_days < stale_days:
            continue

        m = _TRDD_NAME_RE.match(f.name)
        if not m:
            continue
        # group(1) = current-format uid8, group(2) = legacy full UUID; exactly
        # one is set. Both feed the dedupe key (unique) and the `[:8]` display.
        uuid = m.group(1) or m.group(2)
        bucket = age_days // 7

        # `active_label` is whatever the human author wrote in the
        # status:/column: frontmatter — fully untrusted text. The narrowing
        # membership check above limits the value to a known set in normal
        # operation, but a future format change could widen it — defang here.
        display_status = state.sanitize_for_drift_line(active_label)
        line = dedupe.emit_once(
            seen,
            f"drift@{uuid}@bucket-{bucket}",
            f"[trdd-drift] TRDD-{uuid[:8]} status='{display_status}' but file untouched for {age_days}d.",
        )
        if line is not None:
            print(line)

    state.rotate_log_if_big("trdd-drift")
    return 0


if __name__ == "__main__":
    sys.exit(main())
