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
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import state  # noqa: E402
import trdd_common  # noqa: E402

# The TRDD filename / frontmatter parsing is shared across the TRDD detectors —
# it lives in trdd_common now (TRDD-15ECPBSA). `extract_uid` is the SINGLE id
# matcher (base36 UPPERCASE id + legacy lowercase-hex/UUID, case preserved): it
# catches the modern uppercase-base36 ids that the old `[0-9a-f]{8}` matcher
# silently DROPPED, so a stale v2 TRDD is no longer invisible to this detector.
_parse_trdd_state = trdd_common.parse_trdd_state
_ACTIVE_COLUMNS = trdd_common.ACTIVE_COLUMNS

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

    # BOTH design scopes — PROJECT (`<repo>/design/tasks`, honoring
    # CLAUDE_PLUGIN_OPTION_TRDD_PATH) and LOCAL (`~/.claude/projects/<slug>/design/tasks`).
    # `trdd_common` owns the resolution AND the containment check that refuses a TRDD_PATH
    # escaping the project root — that check lived here as a private copy, which is exactly
    # how a second root gets missed by one consumer and its tasks go invisible.
    trdds = trdd_common.trdd_files("tasks", str(root))
    if not trdds:
        state.log_line("trdd-drift", "no TRDDs in any design scope — skipping")
        return 0

    now = int(time.time())

    for scope, f in trdds:
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

        # PROJECT TRDDs are git-tracked, so their last-commit time is the honest "last
        # touched" (an mtime is churned by any checkout). A LOCAL TRDD lives OUTSIDE the
        # repo and is in no git at all — asking git about it is meaningless, so use its
        # mtime directly rather than relying on `git log` to fail quietly on a foreign path.
        touched = (
            _last_touched_epoch(f, root)
            if scope == trdd_common.PROJECT
            else state.file_mtime(f)
        )
        if touched == 0:
            continue

        age_days = (now - touched) // 86400
        if age_days < stale_days:
            continue

        # The SINGLE id matcher: base36 UPPERCASE id or legacy UUID, case
        # preserved; None for a non-TRDD filename. Feeds the dedupe key (unique)
        # and the `[:8]` display ref.
        uuid = trdd_common.extract_uid(f.name)
        if uuid is None:
            continue
        bucket = age_days // 7

        # `active_label` is whatever the human author wrote in the
        # status:/column: frontmatter — fully untrusted text. The narrowing
        # membership check above limits the value to a known set in normal
        # operation, but a future format change could widen it — defang here.
        display_status = state.sanitize_for_drift_line(active_label)
        # Name the scope only when it is LOCAL — PROJECT is the default board, and tagging
        # every line with it would be noise. TRDD ids are globally unique, so the dedupe key
        # needs no scope qualifier.
        tag = " (local)" if scope == trdd_common.LOCAL else ""
        line = dedupe.emit_once(
            seen,
            f"drift@{uuid}@bucket-{bucket}",
            f"[trdd-drift] TRDD-{uuid[:8]}{tag} status='{display_status}' but file untouched for {age_days}d.",
        )
        if line is not None:
            print(line)

    state.rotate_log_if_big("trdd-drift")
    return 0


if __name__ == "__main__":
    sys.exit(main())
