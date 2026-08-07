#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""PreToolUse hook — deny an edit to a repo while its `publish.py` is running.

Vector: an agent edits a source file WHILE `scripts/publish.py` is mid-run on the
same repo. `publish.py` snapshots the tree, runs its (slow) lint/test/validate
stages, then re-checks the tree before committing — a concurrent edit trips its
real-state write guard ("[source-tree] CHANGED: ...") and fails the whole publish,
wasting the entire run (measured: ~10 minutes, twice, in one session). This guard
makes that mechanically impossible instead of relying on discipline: `publish.py`
writes `.janitor/state/publish-in-progress.json` for the duration of its run (see
"-- Publish lock --" in publish.py), and this hook denies Edit/Write/MultiEdit/
NotebookEdit on that repo while the lock is live.

LESSON (same one every janitor hook here re-learns): an unreadable payload, an
unresolvable path, or ANY exception MUST allow — a hook that blocks editing
because IT crashed is worse than the bug it exists to prevent. Every failure path
below returns 0 (allow).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

_COVERED_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
_MAX_AGE_ENV = "CLAUDE_PLUGIN_OPTION_PUBLISH_LOCK_MAX_AGE_S"
_DEFAULT_MAX_AGE_S = 3600


def _target_path(tool_input: dict) -> str:
    """The file/notebook path a covered tool's `tool_input` targets, or ''."""
    if not isinstance(tool_input, dict):
        return ""
    path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    return path if isinstance(path, str) else ""


def _repo_root_for(path: Path) -> Path | None:
    """Walk up from `path` (or its parent, if `path` is a file that may not exist
    yet) to the nearest dir containing a `.git` entry. None if none is found."""
    start = path if path.is_dir() else path.parent
    try:
        start = start.resolve()
    except OSError:
        return None
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _lock_pid_is_live(lock: dict) -> bool:
    pid = lock.get("pid")
    if not isinstance(pid, int):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just owned by someone else — still live
    except OSError:
        return False
    return True


def _lock_is_stale(lock: dict, *, max_age_s: int) -> bool:
    started = lock.get("started")
    if not isinstance(started, (int, float)):
        return True
    return (time.time() - started) > max_age_s


def _deny_reason() -> str:
    return (
        "[publish-lock] A `publish.py` release is running on this repo right now. "
        "Editing the working tree mid-run trips publish's own real-state write "
        "guard and fails the release. Wait for the publish to finish (or fail), "
        "then edit."
    )


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # unreadable payload → allow
    if not isinstance(data, dict):
        return 0

    if data.get("tool_name", "") not in _COVERED_TOOLS:
        return 0
    tool_input = data.get("tool_input") or {}
    raw_path = _target_path(tool_input)
    if not raw_path:
        return 0

    try:
        target = Path(raw_path)
    except (TypeError, ValueError):
        return 0

    repo_root = _repo_root_for(target)
    if repo_root is None:
        return 0  # path outside any repo — allow

    lock_file = repo_root / ".janitor" / "state" / "publish-in-progress.json"
    try:
        if not lock_file.is_file():
            return 0
        lock = json.loads(lock_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return 0  # unparseable/missing lock → allow
    if not isinstance(lock, dict):
        return 0

    try:
        max_age_s = int(os.environ.get(_MAX_AGE_ENV, _DEFAULT_MAX_AGE_S))
    except ValueError:
        max_age_s = _DEFAULT_MAX_AGE_S

    if not _lock_pid_is_live(lock):
        return 0
    if _lock_is_stale(lock, max_age_s=max_age_s):
        return 0

    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": _deny_reason(),
        },
    }
    json.dump(out, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
