#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""report-to-trdd-drift — nudge when a DECISION report has no TRDD.

Enforces the "reports are evidence; decisions become TRDDs" rule
(`~/.claude/rules/trdd-design-tasks.md`). A report under `reports/` is gitignored
and ephemeral; a DECISION that lives only in a report is invisible to the next
session (this is exactly how a recommended STACK in a consolidated audit report
got re-derived from scratch). This detector scans `reports/` for decision/synthesis
-class reports that NO TRDD references and reminds the agent to convert each into
a TRDD (new, or by extending an existing one's STATE block).

WHY a heartbeat detector and NOT a Write/Stop hook: reports are frequently written
by SUBAGENTS, whose tool calls a main-session PostToolUse/Stop hook does not
reliably observe; and a report is born ON DISK regardless of who wrote it. Scanning
the folder catches every report. It is a REMINDER (not a hard block) because not
every report is a decision — a Stop-block would false-positive on data-only reports.
Per-report-set tick-bucket dedupe keeps it to once per interval until converted.

Silent when the project has no `design/tasks/` (it doesn't use TRDDs) or no
unconverted decision report. Project-scoped; never touches user/global scope.
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

# Filenames that signal a DECISION / synthesis worth a TRDD (vs raw data dumps,
# lint captures, screenshots — those legitimately stay as evidence-only reports).
_DECISION_RE = re.compile(
    r"(consolidat|synthes|verdict|recommendation|proposal|decision|roadmap|[-_]plan)",
    re.IGNORECASE,
)
_FRESH_GRACE_S = 90  # skip reports written in the last 90s (may be mid-write)
_MAX_LISTED = 6      # cap how many unconverted reports we name in one line


def _session_key() -> str:
    """Session-scoped dedupe key (mirrors trdd-reminder: no PPID — it rotates)."""
    sid = os.environ.get("CLAUDE_SESSION_ID")
    if sid:
        return sid
    host = socket.gethostname().split(".")[0]
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    return hashlib.sha1(f"{host}@{today}".encode("utf-8")).hexdigest()[:12]


def _contained(child: Path, root: Path) -> bool:
    """True iff `child` resolves inside `root` (refuse to scan escapes)."""
    try:
        child.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _trdd_corpus(tasks_dir: Path) -> str:
    """Concatenate all TRDD bodies so a one-shot substring test answers
    'is this report referenced by any TRDD?' (TRDDs cite the report path)."""
    parts: list[str] = []
    for p in sorted(tasks_dir.glob("TRDD-*.md")):
        try:
            parts.append(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(parts)


def main() -> int:
    state.init_state()
    interval = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_REPORT_TO_TRDD_INTERVAL"), 21600
    )

    root = state.project_root()
    tasks_dir = root / os.environ.get("CLAUDE_PLUGIN_OPTION_TRDD_PATH", "design/tasks").rstrip("/")
    reports_dir = root / "reports"

    # Gate: only projects that USE TRDDs and HAVE a reports/ tree. Both must be
    # contained in the project root (no symlink escape).
    if not (tasks_dir.is_dir() and _contained(tasks_dir, root)):
        return 0
    if not (reports_dir.is_dir() and _contained(reports_dir, root)):
        return 0

    corpus = _trdd_corpus(tasks_dir)
    now = int(time.time())

    unconverted: list[str] = []
    for rep in sorted(reports_dir.rglob("*.md")):
        if not _DECISION_RE.search(rep.name):
            continue
        mtime = state.file_mtime(rep)
        if mtime > 0 and (now - mtime) < _FRESH_GRACE_S:
            continue  # too fresh — may still be writing
        # Referenced by any TRDD (cited by basename) → already converted.
        if rep.name in corpus:
            continue
        try:
            rel = str(rep.relative_to(root))
        except ValueError:
            rel = rep.name
        unconverted.append(rel)

    if not unconverted:
        return 0

    listed = unconverted[:_MAX_LISTED]
    more = "" if len(unconverted) <= _MAX_LISTED else f" (+{len(unconverted) - _MAX_LISTED} more)"

    # Tick-bucket dedupe keyed by the SET of unconverted reports — a NEW
    # decision report produces a fresh key (fresh reminder); an unchanged set
    # reminds at most once per interval. Sort so directory order is irrelevant.
    sig = hashlib.sha1(",".join(sorted(unconverted)).encode("utf-8")).hexdigest()[:8]
    tick_key = f"tick-{now // interval}-{sig}"

    seen = state.state_dir() / f"report-to-trdd-session-{_session_key()}.txt"
    msg = (
        f"[report-to-trdd] {len(unconverted)} decision/synthesis report(s) not yet "
        f"converted to a TRDD: {', '.join(listed)}{more}. Reports are gitignored/ephemeral "
        f"— write each decision into a TRDD (new, or extend an existing STATE block) and "
        f"cite the report, so the plan survives the next resume."
    )
    line = dedupe.emit_once(seen, tick_key, msg)
    if line is not None:
        print(line)

    state.rotate_log_if_big("report-to-trdd-drift")
    return 0


if __name__ == "__main__":
    sys.exit(main())
