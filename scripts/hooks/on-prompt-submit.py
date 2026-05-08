#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""UserPromptSubmit hook — Python port of on-prompt-submit.sh.

Fires when the user types a prompt. Refreshes the idle timer so the
heartbeat doesn't emit stale keepalive cues.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

_PLUGIN_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
if not _PLUGIN_ROOT:
    print("[on-prompt-submit] CLAUDE_PLUGIN_ROOT unset; skipping", file=sys.stderr)
    sys.exit(0)

sys.path.insert(0, str(Path(_PLUGIN_ROOT) / "scripts" / "lib"))

import state  # noqa: E402


def main() -> int:
    state.init_state()
    state.atomic_write(state.state_dir() / "last-activity.ts", str(int(time.time())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
