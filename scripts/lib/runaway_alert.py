"""The daemon -> session broadcast channel for runaway kills (TRDD-5G66S0HK).

The janitor already has exactly the right shape for this: the OAuth
rotator writes ONE file into the machine-wide global-state dir and
`dispatch.py::_phase_rotator_alert` prints ONE drift line per session
from it. This module is that pattern again, for a different condition.

WHY ONE FILE IN THE GLOBAL STATE DIR, and not a write into every
project's state dir: the daemon does not know the project set. The
population of sessions is `fleet_scan.gather_fleet()`'s live project
roots, and the daemon has no business enumerating them.

THE PAYLOAD IS HOST-LEVEL AND IDENTICAL FOR EVERY PROJECT, and that is
a legal requirement, not a convenience. The per-project channeling
invariant (TRDD-X92VBFNF, owner directive 2026-07-17) says an automatic
surface may carry information about EXACTLY the project it fires in. A
kill event is about the HOST, so it may only be broadcast as a
host-level payload that is the same for every project. Concretely: the
payload may name the pid, the process's BASE NAME, its RSS, its age and
the pressure readings — and must NEVER carry a project path, a project
name, or a command line that carries one.

THE LINE IS DESCRIPTIVE, NEVER IMPERPATIVE. "killed pid 1234 node
(rss 2100MB, age 7200s) — host swap exhausted" states what happened. It
does not tell the reader what to do. This codebase has already been
burned by imperative status lines being executed by autonomous readers.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

ALERT_NAME = "runaway-alert.json"

# The kill is broadcast at most once per this interval for an UNCHANGED
# (pid, name, reason) signature. A standing condition must not reprint
# on every fire — the model re-reads it every heartbeat and the cost is
# real.
REPEAT_S = 3600

# The ledger's `msg` cap (findings_ledger.MAX_MSG_CHARS). The kill
# record's own message is written to the affected project's ledger, so
# it must fit the same budget. The CONSEQUENCE leads, because the cap
# truncates the tail.
MAX_MSG_CHARS = 120


def _read_json(path: Path) -> dict:
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def kill_record(
    *,
    pid: int,
    name: str,
    rss_mb: int,
    age_s: int,
    reason: str,
    readings: str,
    at: Optional[float] = None,
) -> dict:
    """One kill, in the shape the daemon writes and the session reads.

    `name` is the process's BASE NAME, never its command line — see the
    module docstring's channeling note. `readings` is the pressure
    reading that triggered the kill, rendered as a short string.
    """
    return {
        "pid": int(pid),
        "name": str(name),
        "rss_mb": int(rss_mb),
        "age_s": int(age_s),
        "reason": str(reason),
        "readings": str(readings),
        "at": float(at if at is not None else time.time()),
    }


def record_kill(root: Path, record: dict) -> None:
    """Write ONE kill record into the global-state dir.

    The file holds the kills since the last time the sessions read them;
    `ack` clears it. A kill that nobody reads is still on disk, so the
    record is durable until a session surfaces it.
    """
    root = Path(root)
    path = root / ALERT_NAME
    data = _read_json(path)
    kills = data.get("kills")
    if not isinstance(kills, list):
        kills = []
    kills.append(record)
    # Keep the file bounded: the last 50 kills is far more than any
    # session will surface, and a file that grows without bound is a
    # disk problem on a machine that is already under pressure.
    data["kills"] = kills[-50:]
    data["written_at"] = time.time()
    try:
        root.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        # A broadcast that cannot be written must never break the kill
        # path: the kill already happened and the daemon's own log has
        # the full detail.
        return


def pending_kills(root: Path, now: float) -> list[dict]:
    """The kills a session should surface now, and the file is left alone.

    The session-side caller decides what to print; this only reads.
    """
    data = _read_json(Path(root) / ALERT_NAME)
    kills = data.get("kills")
    if not isinstance(kills, list):
        return []
    out: list[dict] = []
    for kill in kills:
        if isinstance(kill, dict):
            out.append(kill)
    return out


def format_line(kill: dict) -> str:
    """The drift line for ONE kill. DESCRIPTIVE, never imperative.

    The order is: what happened, then the fact that made it happen, then
    the pressure that justified it. The consequence leads so that a
    truncated tail drops the least important word.
    """
    pid = kill.get("pid", "?")
    name = kill.get("name", "?")
    rss = kill.get("rss_mb", "?")
    age = kill.get("age_s", "?")
    reason = kill.get("reason", "host pressure")
    readings = kill.get("readings", "")
    line = (
        f"runaway guard: killed pid {pid} {name} "
        f"(rss {rss}MB, age {age}s) — {reason}"
    )
    if readings:
        line += f" [{readings}]"
    return line


def drift_parts(root: Path, now: float) -> list[str]:
    """The kill lines a session should print, one per kill.

    A kill is printed ONCE: the daemon's file is cleared by `ack` after
    the sessions have had a chance to read it, and the per-session stamp
    below stops a second session printing the same kill twice in its own
    turn.
    """
    kills = pending_kills(root, now)
    lines: list[str] = []
    for kill in kills:
        sig = f"{kill.get('pid')}:{kill.get('name')}:{kill.get('reason')}"
        lines.append(f"{sig}\t{format_line(kill)}")
    return lines
