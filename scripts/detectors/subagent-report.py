#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Subagent report detector — Python port of subagent-report.sh.

Nudges Claude Code to act on recent subagent report files in docs_dev/,
tests/scenarios/reports/, scripts_dev/ that have not yet been referenced
in any commit message. Catches the 'agent wrote a report but the
findings were never acted upon' drift pattern.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import state  # noqa: E402


_SCAN_DIRS = ("docs_dev", "tests/scenarios/reports", "scripts_dev")
_MAX_EMIT_PER_FIRE = 5


def _path_or_parent_referenced(rel: str, scan_dir: str, commits: str) -> bool:
    """True if `rel` OR any of its parent directories appears in `commits`.

    Handles the common case where a commit references a parent directory
    (e.g. a timestamped backup snapshot folder) as a single logical
    artifact, rather than listing every file inside it. Without the
    walk-up, every file under such a directory was reported as
    unreferenced even though the parent was explicitly committed.

    We stop before reaching the scan dir itself because bare names like
    'docs_dev' are too generic — any unrelated commit message that
    happens to mention 'docs_dev' would suppress legitimate orphan alerts.
    """
    if not commits:
        return False
    p = rel
    while True:
        if p in commits:
            return True
        parent = p.rsplit("/", 1)[0] if "/" in p else ""
        if parent == p or parent == scan_dir or not parent:
            return False
        p = parent


def main() -> int:
    state.init_state()

    seen = state.state_dir() / "subagent-report-seen.txt"
    lookback = state.coerce_int(os.environ.get("CLAUDE_PLUGIN_OPTION_SUBAGENT_REPORT_LOOKBACK"), 86400)

    proc = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=str(state.project_root()),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        state.log_line("subagent-report", "not a git repo — skipping")
        return 0

    root = state.project_root()
    now = int(time.time())
    cutoff = now - lookback

    # Collect last-7-days commit messages once so we can match filenames
    # cheaply via substring search inside the loop.
    log_proc = subprocess.run(
        ["git", "log", "--since=7 days ago", "--pretty=format:%s %b"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    commit_bodies = log_proc.stdout if log_proc.returncode == 0 else ""

    count = 0
    for d in _SCAN_DIRS:
        if count >= _MAX_EMIT_PER_FIRE:
            break
        full = root / d
        if not full.is_dir():
            continue
        for f in full.rglob("*.md"):
            if not f.is_file():
                continue
            if count >= _MAX_EMIT_PER_FIRE:
                break

            mtime = state.file_mtime(f)
            if mtime == 0 or mtime < cutoff:
                continue
            age = now - mtime
            try:
                rel = str(f.relative_to(root))
            except ValueError:
                continue

            # Match the full project-relative path against recent commit
            # messages, walking up parent directories so a commit that
            # references a parent (e.g. a timestamped backup snapshot
            # folder) suppresses per-file alerts for everything inside it.
            # Walk stops before the scan dir itself, so generic mentions of
            # 'docs_dev' don't silence real orphan reports. Full paths are
            # matched (not basenames) — a short name like 'notes.md' would
            # false-match commit bodies that mention 'notes' in any
            # unrelated way.
            if _path_or_parent_referenced(rel, d, commit_bodies):
                continue

            age_h = age // 3600
            bucket = age // 86400
            # `rel` comes from the project's filesystem (any user with
            # write access to docs_dev/ or scripts_dev/ controls it).
            # Defang `[`/`]` for the prose; keep raw `rel` in the dedup
            # key so dedup behaviour is unaffected.
            display_rel = state.sanitize_for_drift_line(rel)
            line = dedupe.emit_once(
                seen,
                f"report@{rel}@d{bucket}",
                f"[subagent-report] {display_rel} ({age_h}h old) has not been referenced in any commit — review and act on it, or commit a note explaining why it's deferred.",
            )
            if line is not None:
                print(line)
                count += 1

    state.rotate_log_if_big("subagent-report")
    return 0


if __name__ == "__main__":
    sys.exit(main())
