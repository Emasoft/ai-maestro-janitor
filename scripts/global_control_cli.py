#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Backing CLI for the MACHINE-WIDE janitor control flags (TRDD-a3fa4d5d).

Thin wrapper over global_state's two distinct global flags, so each flag path has
ONE source of truth (never duplicated into a skill's bash):

    global_control_cli.py disarm [reason]   # /janitor-global-disarm — TRUE STOP
    global_control_cli.py arm                # /janitor-global-arm    — revive after a disarm
    global_control_cli.py pause [reason]     # /janitor-global-pause  — SUSPEND (idle, no teardown)
    global_control_cli.py unpause            # /janitor-global-unpause— resume after a pause
    global_control_cli.py status             # show both flags

Two SEPARATE mechanisms, deliberately distinct:
  * DISARM = the kill-switch. The running daemon EXITS on its next loop, and
    per-session heartbeats stop re-spawning it. Revive = `arm`.
  * PAUSE  = the global-pause flag. The daemon stays ALIVE but idles (skips all task
    workloads, keeps ticking its heartbeat), and every session's heartbeat no-ops —
    a teardown-free temporary silence. Revive = `unpause` (instant, no re-spawn).

`status` is the safe read-only default. Exits 0 on success; prints a one-line result.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import global_state as gs  # noqa: E402  (bare sibling import; lib/ is on sys.path)


def _status_line() -> str:
    if gs.kill_switch_present():
        return "DISARMED (kill-switch set — daemon stopped; run /janitor-global-arm to revive)"
    if gs.global_pause_present():
        return "PAUSED (daemon idle; run /janitor-global-unpause to resume)"
    return "RUNNING (no global stop or pause)"


def main() -> int:
    argv = sys.argv[1:]
    cmd = argv[0] if argv else "status"
    reason = " ".join(argv[1:]) if len(argv) > 1 else ""
    if cmd == "disarm":
        gs.set_kill_switch(reason)
        print("janitor globally DISARMED — the daemon will exit on its next loop, and "
              "per-session heartbeats will not re-spawn it. Run "
              "/janitor-global-arm to revive.")
        return 0
    if cmd == "arm":
        gs.clear_kill_switch()
        print("janitor global disarm cleared — the daemon may be (re)spawned again.")
        return 0
    if cmd == "pause":
        gs.set_global_pause(reason)
        print("janitor globally PAUSED — the daemon stays alive but idles (no tasks), and "
              "every session's heartbeat goes silent. Run /janitor-global-unpause to resume.")
        return 0
    if cmd == "unpause":
        gs.clear_global_pause()
        print("janitor global pause lifted — the daemon resumes running tasks and sessions "
              "resume emitting drift.")
        return 0
    if cmd == "status":
        print(_status_line())
        return 0
    sys.exit(f"unknown command: {cmd!r} (use: disarm [reason] | arm | pause [reason] | unpause | status)")


if __name__ == "__main__":
    sys.exit(main())
