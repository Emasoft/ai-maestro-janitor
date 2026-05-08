#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.10"
# ///
"""SessionStart hook — Python port of on-session-start.sh.

Initializes .janitor state and reminds Claude to arm the heartbeat cron
if this is a fresh session. Runs as part of the plugin's hook lifecycle,
NOT at cron-fire time.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

_PLUGIN_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
if not _PLUGIN_ROOT:
    print("[on-session-start] CLAUDE_PLUGIN_ROOT unset; skipping", file=sys.stderr)
    sys.exit(0)

sys.path.insert(0, str(Path(_PLUGIN_ROOT) / "scripts" / "lib"))

import state  # noqa: E402


def main() -> int:
    state.init_state()

    # Clear any stale flag from a prior session crash. If the last session
    # ended mid-rate-limit, the flag is preserved and the heartbeat cron
    # will emit a resume cue on its next fire — which is what we want.
    # So only clear flags that cannot represent valid cross-session state.
    keepalive = state.state_dir() / "keepalive-sent.flag"
    try:
        keepalive.unlink()
    except FileNotFoundError:
        pass

    state.atomic_write(state.state_dir() / "last-activity.ts", str(int(time.time())))
    state.log_line("session-start", f"state initialized at {state.state_dir()}")

    # Stdout from this hook becomes additional context for the first user
    # turn. Remind Claude to arm the heartbeat cron. /janitor-arm is
    # idempotent, so even if the durable cron survived a previous
    # session, re-arming is safe.
    print(
        "[ai-maestro-janitor] The janitor heartbeat keeps drift detection and rate-limit recovery "
        "running in this session. If you have not done so yet (or if the previous cron hit its 7-day "
        "auto-expiry), run /janitor-arm to arm it. The skill is idempotent — safe to re-run."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
