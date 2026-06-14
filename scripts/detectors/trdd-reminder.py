#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""TRDD reminder — Python port of trdd-reminder.sh.

Consolidated reminder of all TRDDs currently active — frontmatter
`status: in-progress` (v1) or a v2 `column:` in the actively-in-flight
set. Uses a time-bucket key for dedupe so the reminder fires at most once
per configured interval even when the heartbeat cron fires more often.
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

# Matches both TRDD filename formats and captures a stable id used for the
# dedupe entry + the short display ref:
#   * current (~/.claude/rules/trdd-design-tasks.md):
#       TRDD-<YYYYMMDD_HHMMSS±HHMM>-<uid-first-8>-<slug>.md  → capture the uid8
#   * legacy: TRDD-<full-UUID>-<slug>.md                     → capture the UUID
# The hex-length floor (8 / 36) prevents the collision the old too-permissive
# regex allowed. The two alternatives are mutually exclusive — a `_` in the
# timestamp can't appear in a UUID, and a UUID has no `_`.
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
# Same set the trdd-drift detector uses.
_ACTIVE_COLUMNS = frozenset(
    {"dev", "testing", "backburner", "todo", "dispatch", "ai_review", "human_review"}
)


def _norm_state(value: str) -> str:
    """Normalise a status/column token to lowercase kebab-case.

    Maps the legacy title-case body values (`In progress`) onto their
    frontmatter spellings (`in-progress`) by lowercasing and collapsing
    internal whitespace to a single hyphen, so a single membership set
    covers both formats.
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
    # Context gate (TRDD-db169d9e R1): TRDD reminders are an ai-maestro/Emasoft
    # framework convention — silent in projects that aren't ai-maestro-plugins
    # members. (Override with JANITOR_FORCE_AI_MAESTRO=1.)
    if not state.project_is_ai_maestro():
        return 0

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
        status, column = _parse_trdd_state(f)
        # Remind about TRDDs that are actively in flight: v1 status
        # `in-progress`, or a v2 column in the actively-in-flight set.
        if status != "in-progress" and column not in _ACTIVE_COLUMNS:
            continue

        m = _TRDD_NAME_RE.match(f.name)
        if not m:
            continue
        # group(1) = current-format uid8, group(2) = legacy full UUID; exactly
        # one is set. Both feed the dedupe entry and the `[:8]` display ref.
        uuid = m.group(1) or m.group(2)

        touched = _last_touched_epoch(f, root, fallback=now)
        age_days = (now - touched) // 86400
        entries.append(f"TRDD-{uuid[:8]} ({age_days}d)")

    if not entries:
        return 0

    # Mix the entries set into the tick_key so a NEW TRDD that flips to
    # active mid-tick produces a fresh key and a fresh reminder
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
        f"[trdd-reminder] {len(entries)} TRDD(s) currently active: {', '.join(entries)}.",
    )
    if line is not None:
        print(line)

    state.rotate_log_if_big("trdd-reminder")
    return 0


if __name__ == "__main__":
    sys.exit(main())
