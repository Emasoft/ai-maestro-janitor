"""Orphaned resume-flag detection (issue #125) — the PURE decision layer.

`resume-after-compact.flag` is written by the PostCompact hook and cleared by the NEXT
heartbeat fire. So an UNCONSUMED flag means exactly one thing: a compaction recorded a
resume target that was never delivered, because that session's heartbeat never fired again
— a dead/expired/never-armed cron, a wedged turn, a crashed CLI.

WHY THIS IS WORTH A DETECTOR AT ALL. The janitor's whole promise is unattended continuity,
and until now its failure mode was SILENT: the only thing that noticed was the human, and
what they noticed was "many dead claude sessions I keep waking by hand". A watchdog whose
own failure is invisible is not a watchdog. This closes the class, not one cause.

The flag is close to a perfect health signal:
  * UNAMBIGUOUS  — it exists iff a resume was recorded and never consumed;
  * SELF-TIMESTAMPING — the `.ts` sidecar is written before the flag, so the age is exact;
  * CROSS-SESSION OBSERVABLE — any process can stat it, which is the point, because the
    session that needs waking is by definition the one that cannot report.

The scan is FILE-based, never process-based, for the same reason: a dead session has no
process to find.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# Fallback staleness window when a project records no armed cadence. Deliberately generous:
# a false "your session is dead" is worse than a late one, because it trains the reader to
# ignore the finding — the exact failure this detector exists to end.
DEFAULT_STALE_SECONDS = 3 * 30 * 60  # 3x the slowest cadence tier (*/30)

# How many transcript lines to read looking for `cwd`. It appears on the first record in
# practice; the cap bounds a corrupt/huge file rather than expressing a real expectation.
_CWD_SCAN_LINES = 40


def project_root_from_transcript(transcript: Path) -> str:
    """The absolute project path a harness transcript belongs to, or "" when unknown.

    The harness dir name is the abs path with every non-alphanumeric char dashed, which is
    LOSSY and cannot be reversed (`/a/b-c` and `/a-b/c` collide). The transcript's own `cwd`
    field is the authoritative source, so read that instead of trying to undo the slug.
    """
    try:
        with transcript.open(encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= _CWD_SCAN_LINES:
                    break
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                cwd = rec.get("cwd") if isinstance(rec, dict) else None
                if isinstance(cwd, str) and cwd.strip():
                    return cwd.strip()
    except OSError:
        return ""
    return ""


def known_project_roots(projects_root: Path) -> list[str]:
    """Every project root the harness has a transcript for, deduped, sorted.

    Enumerates from the harness's own per-project dirs rather than from a configured
    workspace path, so it works on any machine without being told where code lives.
    """
    roots: set[str] = set()
    try:
        entries = sorted(Path(projects_root).iterdir())
    except OSError:
        return []
    for d in entries:
        if not d.is_dir():
            continue
        try:
            transcripts = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            continue
        for t in transcripts[:1]:  # newest only — one read per project
            root = project_root_from_transcript(t)
            if root:
                roots.add(root)
    return sorted(roots)


def cadence_seconds(cron: str) -> int | None:
    """Seconds between fires for a `*/N * * * *` cron, or None when not that shape.

    Only the minute-step form the janitor arms is understood. Anything else returns None so
    the caller falls back to the default window rather than inventing a period from a cron
    it cannot actually read.
    """
    field = (cron or "").strip().split(" ")[0] if cron else ""
    if not field.startswith("*/"):
        return None
    step = field[2:]
    if not step.isdigit():
        return None
    n = int(step)
    return n * 60 if 0 < n <= 60 else None


def stale_window(armed_cron: str, *, factor: int = 3) -> int:
    """The age past which an unconsumed flag is a FINDING, from that project's own cadence.

    `factor` fires (default 3) is the same tolerance `fleet_scan.stale_threshold_for` uses
    for transcript staleness — one missed fire is a hiccup, three is a pattern.
    """
    period = cadence_seconds(armed_cron)
    return period * factor if period else DEFAULT_STALE_SECONDS


def read_armed_cron(state_dir: Path) -> str:
    """That project's last-armed cadence, or "" when it never recorded one."""
    try:
        return (state_dir / "armed-cadence.cron").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def flag_age(state_dir: Path, *, now: int) -> int | None:
    """Seconds since the resume flag was written, or None when there is no flag.

    Prefers the `.ts` sidecar the PostCompact hook writes BEFORE the flag (so it cannot be
    newer than the flag), falling back to the flag's own mtime.
    """
    flag = state_dir / "resume-after-compact.flag"
    try:
        if not flag.exists():
            return None
    except OSError:
        return None
    stamp = state_dir / "resume-after-compact.ts"
    try:
        raw = stamp.read_text(encoding="utf-8").strip()
        if raw.isdigit():
            return max(0, now - int(raw))
    except (OSError, ValueError):
        pass
    try:
        return max(0, now - int(flag.stat().st_mtime))
    except OSError:
        return None


def is_orphaned(age_s: int | None, armed_cron: str, *, factor: int = 3) -> bool:
    """PURE: is a flag of this age, on a project armed at this cadence, orphaned?"""
    if age_s is None:
        return False
    return age_s >= stale_window(armed_cron, factor=factor)


def scan(projects_root: Path, *, now: int, factor: int = 3) -> list[dict]:
    """Every project holding an ORPHANED resume flag: `[{root, age_s, armed_cron}]`.

    Ordered oldest-first so the worst case leads. Never raises — an unreadable project is
    skipped, because a scan that dies on one bad directory reports nothing about the other
    forty-three.
    """
    found: list[dict] = []
    for root in known_project_roots(projects_root):
        state_dir = Path(root) / ".janitor" / "state"
        age = flag_age(state_dir, now=now)
        if age is None:
            continue
        cron = read_armed_cron(state_dir)
        if is_orphaned(age, cron, factor=factor):
            found.append({"root": root, "age_s": age, "armed_cron": cron})
    found.sort(key=lambda f: f["age_s"], reverse=True)
    return found


def format_finding(age_s: int, armed_cron: str) -> str:
    """The one-line ledger message for ONE affected project. Carries no other project's
    name — the finding is recorded into the AFFECTED project's own ledger, per the
    per-project channeling invariant (TRDD-X92VBFNF)."""
    hours = age_s / 3600.0
    age = f"{hours:.1f}h" if hours < 48 else f"{hours / 24:.1f}d"
    cron = armed_cron or "never armed"
    return (
        f"resume never delivered: a compaction recorded a resume target {age} ago and no "
        f"heartbeat has consumed it (cadence: {cron}). This session's cron is dead, expired "
        f"or never armed — run /janitor-arm in it."
    )


def project_slug(root: str) -> str:
    """The trailing path component, for a log line that names the project without leaking
    the absolute path (which carries the machine's user name)."""
    return os.path.basename(root.rstrip("/")) or root
