#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Backing CLI for the machine-wide janitor STOP/start (TRDD-56d24c02 follow-up).

Thin wrapper over global_state's kill-switch primitives so the flag path has ONE
source of truth (never a path duplicated into a skill's bash):

    kill_switch_cli.py set [reason]   # /janitor-stop  → daemon exits + keepalive removed
    kill_switch_cli.py clear          # /janitor-arm   → revive (lazy-spawn allowed again)
    kill_switch_cli.py status         # is the janitor stopped?

`set` is the global STOP: the running daemon sees the flag on its next loop and exits
(removing its OS keepalive on the way out), and per-session heartbeats stop spawning a
new one. `clear` reverses it. Exits 0 on success; prints a one-line status.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import global_state as gs  # noqa: E402  (bare sibling import; lib/ is on sys.path)


def main() -> int:
    argv = sys.argv[1:]
    cmd = argv[0] if argv else "status"
    if cmd == "set":
        reason = " ".join(argv[1:]) if len(argv) > 1 else ""
        gs.set_kill_switch(reason)
        print("janitor STOPPED — kill-switch set; the daemon will exit on its next "
              "loop and per-session heartbeats will not re-spawn it. Run /janitor-arm "
              "to revive.")
        return 0
    if cmd == "clear":
        gs.clear_kill_switch()
        print("janitor kill-switch cleared — the daemon may be (re)spawned again.")
        return 0
    if cmd == "status":
        stopped = gs.kill_switch_present()
        print("STOPPED (kill-switch set)" if stopped else "RUNNING (no kill-switch)")
        return 0
    sys.exit(f"unknown command: {cmd!r} (use: set [reason] | clear | status)")


if __name__ == "__main__":
    sys.exit(main())
