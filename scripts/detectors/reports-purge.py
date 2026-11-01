#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""reports-purge — S8 of the fseventsd plan (TRDD-LCO8229M): bound the janitor's own FS churn
with a line-cap for stale seen-files.

Forensics on the 39 GB fseventsd runaway (TRDD-ZNN0UK5K) tied disk pressure and fsevents volume
to high-rate automated FS churn. The janitor contributes via per-project `.janitor/state`
seen-files that were never pruned. This detector caps them.

**seen-file line cap** — every `.janitor/state/*seen*` dedupe file is capped to its NEWEST
`CLAUDE_PLUGIN_OPTION_SEEN_FILE_MAX_LINES` lines (default 500; 0 disables).
`dedupe.emit_once` appends new keys at the tail, so keeping the tail preserves the most recent
dedupe horizon — old hashes whose findings long since scrolled away are dropped, and the file
stops growing unbounded.

TRDD-KSUIEPTQ (issue #350): this detector USED to also age-purge `reports/` (30 days). That half
is removed. `reports/` is git-tracked project content (owner rule 2026-11-01), so deleting its
files by age destroyed real work and made every project's tree dirty; and `reports_dev/` holds
the raw material those reports are distilled from, whose contents are never deleted (RULE 0).
Nothing under `reports/` or `reports_dev/` is touched here.

What this detector NEVER touches: symlinks; anything outside `.janitor/state/*seen*`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import state  # noqa: E402


def _trim_seen_files(max_lines: int) -> int:
    """Cap every .janitor/state *seen* file to its newest `max_lines` lines.

    dedupe.emit_once APPENDS keys, so the tail is the newest horizon — trimming the head
    keeps dedupe working for everything still on screen while bounding growth.
    """
    trimmed = 0
    for seen in sorted(state.state_dir().glob("*seen*")):
        if seen.is_symlink() or not seen.is_file():
            continue
        try:
            lines = seen.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        if len(lines) <= max_lines:
            continue
        state.atomic_write(seen, "\n".join(lines[-max_lines:]) + "\n")
        trimmed += 1
        state.log_line(
            "reports-purge", f"trimmed seen-file '{seen.name}' {len(lines)} -> {max_lines} lines"
        )
    return trimmed


def main() -> int:
    state.init_state()

    if not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_REPORTS_PURGE_ENABLED", True):
        return 0

    seen_cap = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_SEEN_FILE_MAX_LINES"), 500,
        detector_name="reports-purge", var_name="CLAUDE_PLUGIN_OPTION_SEEN_FILE_MAX_LINES",
    )

    trimmed = 0
    if seen_cap > 0:
        trimmed = _trim_seen_files(seen_cap)

    if trimmed:
        print(f"[reports-purge] capped {trimmed} seen-file(s) to their newest {seen_cap} lines.")

    state.rotate_log_if_big("reports-purge")
    return 0


if __name__ == "__main__":
    sys.exit(main())
