#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""reports-purge — S8 of the fseventsd plan (TRDD-LCO8229M): bound the janitor's own
FS churn with age-based retention for reports/ and a line-cap for stale seen-files.

Forensics on the 39 GB fseventsd runaway (TRDD-ZNN0UK5K) tied both disk pressure and
fsevents volume to high-rate automated FS churn. The janitor contributes via hundreds of
timestamped `reports/<component>/` files and per-project `.janitor/state` seen-files that
were never pruned. This detector extends the existing purge pattern (screenshot-purge /
trashcan-purge) — it does not invent a new one.

Two independent policies per fire:

1. **reports/ age retention** — any regular file under `<project>/reports/**` older than
   `CLAUDE_PLUGIN_OPTION_REPORTS_MAX_AGE_DAYS` (default 30; 0 disables this half) is
   removed with plain `rm` semantics: reports are regeneratable agent output, gitignored
   by rule (`agent-reports-location.md`) — NOT safe-delete/trashcan material, which would
   just MOVE the churn. `reports/screenshots/` is EXCLUDED: screenshot-purge owns that
   subtree with its stricter 72 h policy (single-ownership — never two policies on one
   file). Now-empty subdirectories are removed bottom-up; `reports/` itself survives.

   Retention note (TRDD-LCO8229M derived task): 30 days comfortably exceeds the
   report→TRDD conversion habit (decisions are written into TRDDs AT decision time per
   `trdd-design-tasks.md`), so no TRDD-cited evidence should ever age out unconverted.
   If a report must outlive the window, copy it into a tracked location — retention is
   the default for the gitignored pile, not an archive policy.

2. **seen-file line cap** — every `.janitor/state/*seen*` dedupe file is capped to its
   NEWEST `CLAUDE_PLUGIN_OPTION_SEEN_FILE_MAX_LINES` lines (default 500; 0 disables).
   `dedupe.emit_once` appends new keys at the tail, so keeping the tail preserves the
   most recent dedupe horizon — old hashes whose findings long since scrolled away are
   dropped, and the file stops growing unbounded.

What this detector NEVER touches: symlinks; `.gitkeep`/`README*` structural files;
anything outside `reports/` + `.janitor/state/*seen*`; the `reports/` dir itself.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import state  # noqa: E402

_KEEP_FILES = frozenset({".gitkeep", "README.txt", "README.md"})
_SCREENSHOTS_SUBDIR = "screenshots"  # owned by screenshot-purge — never touched here


def _iter_report_files(reports_dir: Path) -> Iterable[Path]:
    """Every purgeable regular file under reports/, excluding the screenshots subtree."""
    for p in sorted(reports_dir.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        if p.name in _KEEP_FILES:
            continue
        rel = p.relative_to(reports_dir)
        if rel.parts and rel.parts[0] == _SCREENSHOTS_SUBDIR:
            continue
        yield p


def _remove_empty_dirs(reports_dir: Path) -> int:
    """Remove now-empty subdirs bottom-up. Keeps reports/ itself and screenshots/."""
    removed = 0
    # Deepest first so parents empty out as children go.
    for d in sorted((p for p in reports_dir.rglob("*") if p.is_dir()), reverse=True):
        if d == reports_dir or d.name == _SCREENSHOTS_SUBDIR:
            continue
        rel = d.relative_to(reports_dir)
        if rel.parts and rel.parts[0] == _SCREENSHOTS_SUBDIR:
            continue
        try:
            next(d.iterdir())
        except StopIteration:
            try:
                d.rmdir()
                removed += 1
            except OSError:
                continue
        except OSError:
            continue
    return removed


def _purge_old_reports(project_root: Path, max_age_days: int, now: int) -> tuple[int, int]:
    """Remove report files older than the window. Returns (count, oldest_age_s)."""
    reports_dir = project_root / "reports"
    if not reports_dir.is_dir():
        return 0, 0
    threshold_s = max_age_days * 86400
    count = 0
    oldest = 0
    for f in _iter_report_files(reports_dir):
        try:
            age = now - int(f.stat().st_mtime)
        except OSError:
            continue
        if age < threshold_s:
            continue
        try:
            f.unlink()
        except OSError as exc:
            state.log_line("reports-purge", f"failed to unlink '{f}': {exc}")
            continue
        count += 1
        oldest = max(oldest, age)
        state.log_line("reports-purge", f"age-purged '{f.relative_to(project_root)}' (age {age // 86400}d)")
    if count:
        _remove_empty_dirs(reports_dir)
    return count, oldest


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

    max_age_days = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_REPORTS_MAX_AGE_DAYS"), 30,
        detector_name="reports-purge", var_name="CLAUDE_PLUGIN_OPTION_REPORTS_MAX_AGE_DAYS",
    )
    seen_cap = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_SEEN_FILE_MAX_LINES"), 500,
        detector_name="reports-purge", var_name="CLAUDE_PLUGIN_OPTION_SEEN_FILE_MAX_LINES",
    )

    now = int(time.time())
    project_root = state.project_root()

    purged = oldest = 0
    if max_age_days > 0:
        purged, oldest = _purge_old_reports(project_root, max_age_days, now)

    trimmed = 0
    if seen_cap > 0:
        trimmed = _trim_seen_files(seen_cap)

    if purged:
        print(
            f"[reports-purge] removed {purged} report file(s) older than {max_age_days}d "
            f"from reports/ (oldest: {oldest // 86400}d)."
        )
    if trimmed:
        print(f"[reports-purge] capped {trimmed} seen-file(s) to their newest {seen_cap} lines.")

    state.rotate_log_if_big("reports-purge")
    return 0


if __name__ == "__main__":
    sys.exit(main())
