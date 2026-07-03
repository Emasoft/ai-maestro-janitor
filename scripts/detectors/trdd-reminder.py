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
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import state  # noqa: E402
import trdd_common  # noqa: E402

# Shared TRDD filename / frontmatter parsing lives in trdd_common now
# (TRDD-15ECPBSA). The reminder uses the SINGLE `extract_uid` id matcher (it
# catches the modern uppercase-base36 ids the old `[0-9a-f]{8}` matcher silently
# dropped), the shared frontmatter regexes, `_norm_state`, and `_HEAD_BYTES` —
# but keeps its OWN `_parse_trdd_state` (3-tuple, with `created:`) and its OWN
# narrower `_ACTIVE_COLUMNS` (the WORK columns only).
_FRONTMATTER_RE = trdd_common.FRONTMATTER_RE
_FM_STATUS_RE = trdd_common.FM_STATUS_RE
_FM_COLUMN_RE = trdd_common.FM_COLUMN_RE
# The TRDD's birth date (issue #59 — TRUE age is days-since-`created:`, not
# days-since-last-edit). ISO 8601 with a local offset, e.g.
# `created: 2026-06-02T11:53:00+0200`; a bare date is also tolerated.
_FM_CREATED_RE = trdd_common.FM_CREATED_RE
# Legacy `**Status:** ...` markdown body line (pre-frontmatter TRDDs only).
_LEGACY_STATUS_RE = trdd_common.LEGACY_STATUS_RE
# Read only the head of the file — frontmatter lives at the very top, and a
# legacy `**Status:**` line sits just under the title.
_HEAD_BYTES = trdd_common.HEAD_BYTES
_norm_state = trdd_common.norm_state

# v2 `column:` values that mean "actively in flight" — the WORK group per the
# TRDD v2 model (~/.claude/rules/trdd-design-tasks.md). Issue #59: this set used
# to also include the ENTRY/DESIGN columns `backburner`/`todo`/`dispatch`, which
# made the reminder nag about deliberately-PARKED proto-TRDDs as "currently
# active" — backburner is the parking lot, the OPPOSITE of active. Only the four
# WORK columns are genuinely active work someone could forget mid-flight. (This
# deliberately DIVERGES from trdd-drift's wider set: drift cares about any TRDD
# whose git state drifted, including parked ones; the reminder only nags about
# active work, so the two detectors legitimately scope differently now.)
_ACTIVE_COLUMNS = frozenset({"dev", "testing", "ai_review", "human_review"})


def _created_epoch(raw: str) -> int | None:
    """Parse a frontmatter `created:` value to an epoch, or None if unparseable.

    Accepts the canonical ISO 8601 + local offset (`2026-06-02T11:53:00+0200`)
    and a bare date (`2026-06-02`). A naive value is interpreted in local time.
    Returns None on any malformed value so the caller can fall back to mtime.
    """
    token = raw.strip().rstrip("\r").strip("'\"")
    try:
        dt = datetime.fromisoformat(token)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()  # treat a naive timestamp as local
    return int(dt.timestamp())


def _parse_trdd_state(path: Path) -> tuple[str, str, int | None]:
    """Return (status, column, created_epoch) for a TRDD.

    `status`/`column` are normalised kebab-case (or ''). `created_epoch` is the
    epoch of the frontmatter `created:` date (issue #59 — true age is measured
    from birth, not last edit), or None when absent/unparseable so the caller
    falls back to the file's last-touched time. Returns ('', '', None) on any
    read error. Reads the frontmatter `status:`/`column:` keys (the documented
    location), falling back to a legacy `**Status:**` body line when the
    frontmatter has no `status:`.
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            head = f.read(_HEAD_BYTES)
    except (FileNotFoundError, OSError):
        return ("", "", None)

    status = ""
    column = ""
    created: int | None = None
    fm = _FRONTMATTER_RE.match(head)
    if fm:
        block = fm.group(1)
        sm = _FM_STATUS_RE.search(block)
        if sm:
            status = _norm_state(sm.group(1))
        cm = _FM_COLUMN_RE.search(block)
        if cm:
            column = _norm_state(cm.group(1))
        crm = _FM_CREATED_RE.search(block)
        if crm:
            created = _created_epoch(crm.group(1))

    # Legacy fallback only when the frontmatter carried no status: key.
    if not status:
        lm = _LEGACY_STATUS_RE.search(head)
        if lm:
            status = _norm_state(lm.group(1))

    return (status, column, created)


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
        status, column, created = _parse_trdd_state(f)
        # Remind about TRDDs that are actively in flight: v1 status
        # `in-progress`, or a v2 column in the actively-in-flight set.
        if status != "in-progress" and column not in _ACTIVE_COLUMNS:
            continue

        # The SINGLE id matcher: base36 UPPERCASE id or legacy UUID, case
        # preserved; None for a non-TRDD filename. Feeds the dedupe entry and
        # the `[:8]` display ref.
        uuid = trdd_common.extract_uid(f.name)
        if uuid is None:
            continue

        # Issue #59 Defect 2: the reminder's load-bearing signal is STALENESS —
        # `idle` = days since the TRDD was last touched (git-commit time, else
        # mtime). The TRUE age (`age` = days since the frontmatter `created:`) is
        # shown as CONTEXT. Showing BOTH — `(idle Nd, age Md)` — removes the old
        # bare-"(Nd)" ambiguity (it read as "age" but was actually days-since-touch,
        # and the prior fix over-corrected to age-only, dropping the staleness the
        # nag exists to surface). `age` is omitted for a legacy TRDD whose
        # frontmatter has no parseable `created:`.
        idle_days = (now - _last_touched_epoch(f, root, fallback=now)) // 86400
        if created is not None:
            label = f"idle {idle_days}d, age {(now - created) // 86400}d"
        else:
            label = f"idle {idle_days}d"
        entries.append(f"TRDD-{uuid[:8]} ({label})")

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
    # max(1, …): interval=0 is a legal knob value (coerce_int only clamps negatives) and
    # must mean "every fire", never ZeroDivisionError — same guard as memorize-nudge.
    tick_key = f"tick-{now // max(1, interval)}-{entries_hash}"
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
