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

    THE REAL LIFECYCLE, which the previous docstring got wrong: it
    claimed the file is cleared by a mechanism that DOES NOT EXIST —
    there is no clearing function anywhere in this module or in the
    dispatch phase that reads it. The truth is:

      * the file is APPEND-ONLY from the daemon's side — the daemon
        writes kills and NEVER clears the file;
      * `record_kill` TRIMS it to the last 50 kills, so it is bounded
        by count, not by age;
      * the suppression of a RE-PRINT is done PER SESSION, by
        `scripts/dispatch.py::_phase_runaway_alert`, which keeps its own
        per-project stamp file (`state_dir()/runaway-alert-printed.txt`)
        of kill signatures it has already printed.

    So a kill stays on disk until it is pushed out of the last 50, and
    a NEW session — which has a NEW per-project stamp — re-prints the
    retained kills. That re-print behaviour is A-4 on TRDD-ZIKYQQY0 and
    is NOT fixed here; this docstring only stops claiming a clearing
    mechanism that does not exist.
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

    THE `now` ARGUMENT IS CURRENTLY UNUSED, and the signature keeps it
    only so the caller in `scripts/dispatch.py::_phase_runaway_alert`
    does not have to change. It is NOT an expiry window: there is no
    time-based filter here, and a reader must not assume one. A kill
    stays "pending" until it is pushed out of the last 50 by
    `record_kill`. The de-duplication of a re-print is the CALLER's job
    (it keeps its own per-project stamp of printed signatures).
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
