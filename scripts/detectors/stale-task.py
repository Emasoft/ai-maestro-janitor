#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Stale task detector — Python port of stale-task.sh.

Nudges Claude Code about tasks that have been sitting `in_progress` or
`pending` for too long without any update. Relies on the mtime of
~/.claude/tasks/<team>/<task>.json as the 'last touched' signal, which
Claude Code updates on every TaskUpdate call.

DEPENDS ON AN OPT-IN HARNESS FEATURE (CC 2.1.233). The task tools that write those
files — TaskCreate/TaskGet/TaskUpdate/TaskList — were removed on Opus 4.8, Sonnet 5,
Fable 5, Mythos 5 and newer, and return only under CLAUDE_CODE_ENABLE_TODO_TOOLS=1.

Be precise about what that means here, because the tree is NOT empty: measured on the
dev host 2026-08-22 it held 635 task files, all but one written before 2026-08-15 —
i.e. by sessions predating the removal. What went away is NEW writes, and this detector
scopes to `_resolve_team_uuid`, the CURRENT session's uuid dir, which a default modern
session never creates. So it scans a directory that does not exist and is CORRECTLY
silent, while a heap of older sessions' tasks sits untouched beside it.

That silence therefore means "this session has no task dir", NOT "no tasks are stale" —
and it is not evidence the feature is unused machine-wide either. Left running rather
than removed: it costs one directory listing, and it is still right on a session that
opted back in.

Coverage, stated accurately because the commit that added this note got it wrong: this
file IS named in `tests/test_scanner_walk_invariants.py:102`, which holds it to the
shared scanner-walk invariants. What it has no test for is its OWN staleness logic —
the thresholds, the team-uuid scoping, the nudge text. Do not read "there are tests
that mention this file" as "this behaviour is pinned".
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import state  # noqa: E402


def _resolve_team_uuid(project_root: Path) -> Optional[str]:
    """Resolve the team UUID for the CURRENT project's most-recent session.

    Claude Code writes per-session logs to
        ~/.claude/projects/<project-slug>/<session-uuid>.jsonl
    where <project-slug> is the project root with `/` rewritten to `-`.
    The basename of the latest .jsonl in that dir matches the session UUID,
    which is also the directory name under ~/.claude/tasks/.

    Picking that dir scopes the detector to this project's tasks and avoids
    the cross-project bleed of enumerating all session task dirs by mtime.
    """
    slug = str(project_root).replace("/", "-")
    session_root = Path.home() / ".claude" / "projects" / slug
    if not session_root.is_dir():
        return None
    jsonls = sorted(session_root.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not jsonls:
        return None
    return jsonls[0].stem


def _read_task_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None


def main() -> int:
    state.init_state()

    seen = state.state_dir() / "stale-task-seen.txt"
    in_progress_threshold = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_STALE_IN_PROGRESS_THRESHOLD"), 7200
    )
    pending_threshold = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_STALE_PENDING_THRESHOLD"), 86400
    )

    team = _resolve_team_uuid(state.project_root())
    if team is None:
        state.log_line("stale-task", "no task directory — skipping")
        return 0

    tasks_dir = Path.home() / ".claude" / "tasks" / team
    if not tasks_dir.is_dir():
        state.log_line("stale-task", f"team dir {tasks_dir} missing — skipping")
        return 0

    now = int(time.time())

    for t in sorted(tasks_dir.glob("*.json")):
        data = _read_task_json(t)
        if not data:
            continue
        task_id = str(data.get("id") or "").strip()
        if not task_id:
            continue
        task_status = str(data.get("status") or "pending")
        subject = str(data.get("subject") or "")

        if task_status == "in_progress":
            threshold = in_progress_threshold
        elif task_status == "pending":
            threshold = pending_threshold
        else:
            continue

        mtime = state.file_mtime(t)
        if mtime == 0:
            continue
        age = now - mtime
        if age < threshold:
            continue

        bucket = age // 86400  # re-emit once per day the task stays stale
        # Subject is fully user-controlled (anything the user / agent
        # passed to TaskCreate). Truncate first to bound the output, then
        # defang `[`/`]` and strip control chars so a subject like
        # `[janitor-resume] do X` cannot mimic our own marker.
        clean_subject = state.sanitize_for_drift_line(subject[:60])
        age_h = age // 3600

        line = dedupe.emit_once(
            seen,
            f"task-{task_id}@{task_status}@d{bucket}",
            f"[stale-task] Task #{task_id} '{clean_subject}' has been {task_status} for ~{age_h}h with no update. "
            f"Resume, close, or defer it. Use TaskUpdate to record progress.",
        )
        if line is not None:
            print(line)

    state.rotate_log_if_big("stale-task")
    return 0


if __name__ == "__main__":
    sys.exit(main())
