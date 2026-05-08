#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""trashcan-purge — Python port of trashcan-purge.sh.

Auto-removes timestamped batches in <project_root>/.trashcan/ whose age
(computed from the folder-name timestamp, NOT file mtimes) exceeds
CLAUDE_PLUGIN_OPTION_TRASHCAN_MAX_AGE_DAYS (default: 90).

Why folder-name timestamps and not mtimes:
  A user (or another tool) could `touch` a file inside an old batch and
  accidentally reset its mtime. The folder name encodes the disposal moment
  that the safe-delete script wrote at trash time, and is immutable for
  the life of the batch — so an old batch stays old regardless of what
  happens to its contents.

Why this detector NEVER touches .gitkeep / README.txt / unrecognised files:
  The trashcan directory is kept alive by tracked .gitkeep + README.txt
  markers (see scripts/safe-delete.sh). Removing those would defeat the
  whole survival mechanism — the dir would vanish on the next
  `git clean -fdx`. The regex matcher below only matches the exact
  timestamp shape; anything else is skipped silently.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import state  # noqa: E402


# Folder/manifest patterns. Either `+HHMM` or `-HHMM` offset. Manifest
# variants carry a trailing `.txt`. Anything else is left alone — that's
# how .gitkeep, README.txt, and any human-added file or folder stay safe.
_TS_FOLDER_RE = re.compile(r"^(\d{8}_\d{6}[+-]\d{4})$")
_TS_MANIFEST_RE = re.compile(r"^(\d{8}_\d{6}[+-]\d{4})\.txt$")


def _parse_ts_to_epoch(ts: str) -> Optional[int]:
    """Parse YYYYMMDD_HHMMSS±HHMM into epoch seconds. None on parse failure."""
    try:
        # `%z` accepts ±HHMM since Python 3.7.
        dt = datetime.strptime(ts, "%Y%m%d_%H%M%S%z")
    except ValueError:
        return None
    return int(dt.timestamp())


def main() -> int:
    state.init_state()

    if not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_TRASHCAN_PURGE_ENABLED", True):
        return 0

    max_age_days = state.coerce_int(os.environ.get("CLAUDE_PLUGIN_OPTION_TRASHCAN_MAX_AGE_DAYS"), 90)
    threshold_sec = max_age_days * 86400

    project_root = state.project_root()
    trash_dir = project_root / ".trashcan"
    if not trash_dir.is_dir():
        return 0

    now = int(time.time())
    purged_count = 0
    purged_oldest_days = 0

    # Sort for deterministic output. We may delete folders + their .txt
    # siblings on the same loop iteration so we work on a snapshot list.
    for entry in sorted(trash_dir.iterdir()):
        name = entry.name
        m_folder = _TS_FOLDER_RE.match(name)
        m_manifest = _TS_MANIFEST_RE.match(name)
        if not (m_folder or m_manifest):
            continue
        ts = (m_folder or m_manifest).group(1)  # type: ignore[union-attr]

        entry_epoch = _parse_ts_to_epoch(ts)
        if entry_epoch is None:
            state.log_line("trashcan-purge", f"could not parse timestamp from '{name}' — skipping")
            continue

        age = now - entry_epoch
        if age < threshold_sec:
            continue
        age_days = age // 86400

        # When we delete a folder, also delete its sibling .txt manifest so
        # we don't leave orphans. When we delete a .txt manifest first
        # (loop order is filesystem-defined but sorted now), that's fine —
        # the folder will follow on its own iteration.
        try:
            if entry.is_dir() and not entry.is_symlink():
                txt_sibling = trash_dir / f"{ts}.txt"
                shutil.rmtree(entry)
                if txt_sibling.is_file():
                    txt_sibling.unlink()
                state.log_line("trashcan-purge", f"purged folder + manifest '{ts}' (age: {age_days}d)")
            elif entry.is_file():
                entry.unlink()
                state.log_line("trashcan-purge", f"purged orphan manifest '{name}' (age: {age_days}d)")
        except OSError as exc:
            state.log_line("trashcan-purge", f"failed to purge '{name}': {exc}")
            continue

        purged_count += 1
        if age_days > purged_oldest_days:
            purged_oldest_days = age_days

    if purged_count > 0:
        print(
            f"[trashcan-purge] auto-removed {purged_count} batch(es) from .trashcan/ older than "
            f"{max_age_days} days (oldest: {purged_oldest_days}d). Folder-name timestamps are the "
            f"source of truth — file mtimes inside batches are ignored."
        )

    state.rotate_log_if_big("trashcan-purge")
    return 0


if __name__ == "__main__":
    sys.exit(main())
