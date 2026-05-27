#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Per-session shim — user-scope plugin updates are owned by the global daemon.

Closes GitHub issue #7. The actual enumeration of user-scope plugins and the
per-plugin `claude plugin update <id> --scope user` invocations moved to
`scripts/daemon.py` — the same singleton daemon that owns marketplace
refresh. The pre-daemon design ran an entire sequential sweep from EACH
Claude Code session in parallel, producing the exact pile-up issue #7
documents (multiple `claude plugin update` workers from different parent
session shells colliding on the same global plugin cache).

This per-session detector now does only two things:
  1. Ensure the daemon is alive (cheap when it already is).
  2. Surface a one-line drift nudge IFF the daemon's user-plugins-update
     task hasn't run for more than 2× its configured cadence — i.e., the
     daemon IS alive but this task is not making progress. Deduped hourly.

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

_NAME = "user-plugins-update"


def main() -> int:
    state.init_state()
    gs.ensure_daemon_running()

    last_run_path = gs.global_state_dir() / "user-plugins-update.last-run.ts"
    last_run = state.read_int_state(last_run_path, 0)
    if last_run <= 0:
        state.rotate_log_if_big(_NAME)
        return 0

    cadence = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_DAEMON_USER_PLUGINS_UPDATE_INTERVAL"),
        3600,
    )
    stale_threshold = 2 * cadence
    age = int(time.time()) - last_run
    if age <= stale_threshold:
        state.rotate_log_if_big(_NAME)
        return 0

    seen = state.state_dir() / "user-plugins-update-stale-seen.txt"
    key = f"stale@{int(time.time() // 3600)}"
    out = dedupe.emit_once(
        seen,
        key,
        gs.build_worker_stale_message(
            worker_tag="user-plugins-update",
            worker_action="swept user-scope plugins",
            age_s=age,
            cadence_s=cadence,
        ),
    )
    if out is not None:
        print(out)

    state.rotate_log_if_big(_NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
