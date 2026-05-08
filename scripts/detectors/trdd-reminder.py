#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""TRDD reminder — Python port of trdd-reminder.sh.

Consolidated reminder of all TRDDs currently 'In progress'. Uses a
time-bucket key for dedupe so the reminder fires at most once per
configured interval even when the heartbeat cron fires more often.
"""

from __future__ import annotations

import hashlib
import os
import re
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import state  # noqa: E402


_TRDD_NAME_RE = re.compile(r"^TRDD-([0-9a-f-]{36})-.+\.md$")
_STATUS_RE = re.compile(r"^\*\*Status:\*\*\s*(.+)$")


def _parse_status(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = _STATUS_RE.match(line)
                if m:
                    return m.group(1).rstrip("\r").strip()
    except (FileNotFoundError, OSError):
        return ""
    return ""


def _last_touched_epoch(path: Path, project_root: Path, fallback: int) -> int:
    """Prefer git last-commit timestamp, fall back to mtime then to `fallback`.

    Bounded by a 5s timeout — `git log -1` is normally instant but a
    corrupted refs pack would otherwise hang the heartbeat.
    """
    proc = state.run_subprocess(
        ["git", "-C", str(project_root), "log", "-1", "--format=%ct", "--", str(path)],
        timeout=5,
        detector_name="trdd-reminder",
    )
    if proc is not None and proc.returncode == 0:
        out = proc.stdout.strip()
        if out.isdigit():
            return int(out)
    mtime = state.file_mtime(path)
    return mtime if mtime > 0 else fallback


def _session_key() -> str:
    """Prefer CLAUDE_SESSION_ID for true session scoping; else hostname+date.

    Bash port deliberately avoids PPID — inside a cron-fire subshell PPID
    is the hook's short-lived shell, different on every fire, so the
    dedupe file rotated every 5 minutes and the reminder re-emitted on
    every heartbeat.
    """
    sid = os.environ.get("CLAUDE_SESSION_ID")
    if sid:
        return sid
    host = socket.gethostname().split(".")[0]
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    digest = hashlib.sha1(f"{host}@{today}".encode("utf-8")).hexdigest()
    return digest[:12]


def main() -> int:
    state.init_state()

    interval = state.coerce_int(os.environ.get("CLAUDE_PLUGIN_OPTION_TRDD_REMINDER_INTERVAL"), 14400)

    root = state.project_root()
    trdd_subpath = os.environ.get("CLAUDE_PLUGIN_OPTION_TRDD_PATH", "design/tasks").rstrip("/")
    trdd_dir = root / trdd_subpath

    # Containment check — see trdd-drift.py for the rationale.
    try:
        resolved_trdd = trdd_dir.resolve()
        resolved_root = root.resolve()
        resolved_trdd.relative_to(resolved_root)
    except (ValueError, OSError):
        state.log_line(
            "trdd-reminder",
            f"TRDD path {trdd_subpath!r} resolves outside project root — refusing to scan",
        )
        return 0

    if not trdd_dir.is_dir():
        state.log_line("trdd-reminder", f"TRDD dir {trdd_dir} not present — skipping")
        return 0

    now = int(time.time())
    session = _session_key()
    seen = state.state_dir() / f"trdd-reminder-session-{session}.txt"

    entries: list[str] = []
    for f in sorted(trdd_dir.glob("TRDD-*.md")):
        status = _parse_status(f)
        if status != "In progress":
            continue

        m = _TRDD_NAME_RE.match(f.name)
        if not m:
            continue
        uuid = m.group(1)

        touched = _last_touched_epoch(f, root, fallback=now)
        age_days = (now - touched) // 86400
        entries.append(f"TRDD-{uuid[:8]} ({age_days}d)")

    if not entries:
        return 0

    # Mix the entries set into the tick_key so a NEW TRDD that flips to
    # 'In progress' mid-tick produces a fresh key and a fresh reminder
    # (instead of being suppressed by the existing tick's dedup entry).
    # The age component (`(Nd)` suffix) is intentionally kept out of the
    # key — re-keying every day for the same TRDD set would defeat the
    # purpose of the time bucket. Sort first so the order TRDDs appear
    # in the directory listing doesn't change the hash.
    entries_signature = ",".join(sorted(e.split(" ", 1)[0] for e in entries))
    entries_hash = hashlib.sha1(entries_signature.encode("utf-8")).hexdigest()[:8]
    tick_key = f"tick-{now // interval}-{entries_hash}"
    line = dedupe.emit_once(
        seen,
        tick_key,
        f"[trdd-reminder] {len(entries)} TRDD(s) currently In progress: {', '.join(entries)}.",
    )
    if line is not None:
        print(line)

    state.rotate_log_if_big("trdd-reminder")
    return 0


if __name__ == "__main__":
    sys.exit(main())
