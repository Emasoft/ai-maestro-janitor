#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Per-session shim — marketplace refresh is owned by the global daemon.

Closes GitHub issue #7. The actual work (`claude plugin marketplace update`)
moved to `scripts/daemon.py`, a system-wide single-instance process
lazy-spawned by every heartbeat via `ensure_daemon_running()`. The pre-daemon
design tracked the worker PID PER PROJECT, which is the bug issue #7
documents: N concurrent Claude Code sessions = N concurrent refresh workers,
because each per-project gate looked at its own state dir and saw "no prior
worker." The daemon's flock-protected singleton fixes that — every session,
every project, every spawn attempt ends up pointing at one OS process.

This per-session detector now does only two things:
  1. Ensure the daemon is alive (cheap when it already is).
  2. Surface a one-line drift nudge IFF the daemon's marketplace refresh
     hasn't run for more than 2× its configured cadence — i.e., the daemon
     IS alive but the task is not making progress (stuck subprocess, broken
     gh auth, etc.). Deduped hourly so a wedged daemon doesn't spam.

Output: silent normally; one drift line per hour while the task is stale.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import global_state as gs  # noqa: E402
import state  # noqa: E402

_NAME = "marketplace-refresh"


def main() -> int:
    state.init_state()
    gs.ensure_daemon_running()

    # The daemon's last-run.ts for this task; the daemon writes it on every
    # successful completion. Missing → either the daemon just started or
    # the task has never finished yet; either way it is NOT proof of staleness.
    last_run_path = gs.global_state_dir() / "marketplace-refresh.last-run.ts"
    last_run = state.read_int_state(last_run_path, 0)
    if last_run <= 0:
        state.rotate_log_if_big(_NAME)
        return 0

    cadence = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_DAEMON_MARKETPLACE_REFRESH_INTERVAL"),
        1800,
    )
    stale_threshold = 2 * cadence
    age = int(time.time()) - last_run
    if age <= stale_threshold:
        state.rotate_log_if_big(_NAME)
        return 0

    # Stale — surface once per UTC hour so a long stall doesn't spam every fire.
    seen = state.state_dir() / "marketplace-refresh-stale-seen.txt"
    key = f"stale@{int(time.time() // 3600)}"
    out = dedupe.emit_once(
        seen,
        key,
        f"[marketplace-refresh] daemon has not refreshed marketplaces in "
        f"~{age // 60} min (cadence {cadence}s) — daemon may be stuck. "
        f"Inspect: ~/.claude/janitor-global-state/daemon.log. "
        f"Restart: kill $(cat ~/.claude/janitor-global-state/daemon.pid).",
    )
    if out is not None:
        print(out)

    state.rotate_log_if_big(_NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
