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
     completion stamp is stale past a generous threshold AND the daemon is
     not responding (dead PID / frozen heartbeat). A heartbeat-fresh daemon
     is NEVER flagged — a long-but-healthy sweep ages the completion stamp
     while the daemon is fine (issue #9). Shared with marketplace-refresh via
     daemon_watchdog so the two shims cannot drift apart. Deduped hourly.

Output: silent normally; one drift line per hour while the daemon is not
responding and the sweep is overdue.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import daemon_watchdog  # noqa: E402
import global_state as gs  # noqa: E402
import state  # noqa: E402

_NAME = "user-plugins-update"


def main() -> int:
    state.init_state()
    gs.ensure_daemon_running()
    daemon_watchdog.emit_if_daemon_stale(
        task_name=_NAME,
        last_run_filename="user-plugins-update.last-run.ts",
        cadence_env="CLAUDE_PLUGIN_OPTION_DAEMON_USER_PLUGINS_UPDATE_INTERVAL",
        default_cadence_s=3600,
        subject="user-scope plugins last swept",
    )
    state.rotate_log_if_big(_NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
