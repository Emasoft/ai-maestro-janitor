#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""TRDD drift detector — Python port of trdd-drift.sh.

One-shot scan for stale 'In progress' / 'Not started' TRDDs.
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

# Matches `TRDD-<full UUID>-<slug>.md`. The 36-char UUID enforcement
# prevents collisions on the dedupe key — older regex was too permissive
# and let `TRDD-deadbeef.md` land uuid="" and collide on `drift@@bucket-N`.
_TRDD_NAME_RE = re.compile(r"^TRDD-([0-9a-f-]{36})-.+\.md$")
# Matches the `**Status:** ...` line in the TRDD body.
_STATUS_RE = re.compile(r"^\*\*Status:\*\*\s*(.+)$")


def _parse_status(path: Path) -> str:
    """Read the first **Status:** line from a TRDD. Returns '' on any error."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = _STATUS_RE.match(line)
                if m:
                    return m.group(1).rstrip("\r").strip()
    except (FileNotFoundError, OSError):
        return ""
    return ""


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
        status = _parse_status(f)
        if status not in ("Not started", "In progress"):
            continue

        touched = _last_touched_epoch(f, root)
        if touched == 0:
            continue

        age_days = (now - touched) // 86400
        if age_days < stale_days:
            continue

        m = _TRDD_NAME_RE.match(f.name)
        if not m:
            continue
        uuid = m.group(1)
        bucket = age_days // 7

        # `status` is whatever the human author wrote in the **Status:**
        # line — fully untrusted text. The narrowing membership check
        # above limits the value to exactly two strings in normal
        # operation, but a future detector that emits free-form status
        # would expose the same surface — defang here for safety.
        display_status = state.sanitize_for_drift_line(status)
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
