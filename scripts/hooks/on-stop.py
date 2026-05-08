#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.10"
# ///
"""Stop hook — Python port of on-stop.sh.

Fires when Claude completes a turn successfully. Resets the idle timer
so the heartbeat's cache-keepalive semantics track the latest activity.
Does NOT clear rate-limited.flag here — that belongs to the heartbeat
itself, since a successful turn after a rate-limit is exactly the
signal that triggers the dispatch [janitor-resume] emission on the
next fire.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

_PLUGIN_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
if not _PLUGIN_ROOT:
    print("[on-stop] CLAUDE_PLUGIN_ROOT unset; skipping", file=sys.stderr)
    sys.exit(0)

sys.path.insert(0, str(Path(_PLUGIN_ROOT) / "scripts" / "lib"))

import state  # noqa: E402


def main() -> int:
    state.init_state()
    state.atomic_write(state.state_dir() / "last-activity.ts", str(int(time.time())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
