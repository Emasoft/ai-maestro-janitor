#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.10"
# ///
"""StopFailure hook — Python port of on-stop-failure.sh.

Fires when an API error (rate-limit, auth failure, etc.) ends the turn
instead of Stop. Writes a flag file that the heartbeat cron's dispatch
reads on its next fire. When the API is reachable again, that fire
succeeds, dispatch sees the flag, clears it, and emits [janitor-resume]
so Claude picks up where it left off.

This is the ONE hook that absolutely must never silently fail — if the
flag isn't written, resume is disabled for this rate-limit window. The
guard below exits 0 with a stderr note rather than non-zero, because
Claude Code treats non-zero hook exits as blocking, and we'd rather
degrade (no resume cue) than block the session on a plugin misconfig.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

_PLUGIN_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
if not _PLUGIN_ROOT:
    print(
        "[on-stop-failure] CLAUDE_PLUGIN_ROOT unset; resume cue will not be captured for this turn",
        file=sys.stderr,
    )
    sys.exit(0)

sys.path.insert(0, str(Path(_PLUGIN_ROOT) / "scripts" / "lib"))

import state  # noqa: E402


def main() -> int:
    state.init_state()
    flag = state.state_dir() / "rate-limited.flag"
    flag.touch()
    state.atomic_write(state.state_dir() / "rate-limited-since.ts", str(int(time.time())))
    state.log_line(
        "stop-failure",
        "rate-limit captured; dispatch will emit resume cue on next heartbeat fire",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
