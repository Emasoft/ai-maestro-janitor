#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Stop hook — Python port of on-stop.sh.

Fires when Claude completes a turn successfully. Currently a no-op: the
previous implementation refreshed a `last-activity.ts` timestamp, but
no detector ever reads it. The hook intentionally does NOT clear
`rate-limited.flag` either — that belongs to the heartbeat itself,
since a successful turn after a rate-limit is exactly the signal that
triggers the dispatch [janitor-resume] emission on the next fire. The
hook is kept registered so future stop-driven behaviour doesn't
require a settings.json edit.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_PLUGIN_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
if not _PLUGIN_ROOT:
    print("[on-stop] CLAUDE_PLUGIN_ROOT unset; skipping", file=sys.stderr)
    sys.exit(0)

sys.path.insert(0, str(Path(_PLUGIN_ROOT) / "scripts" / "lib"))


def main() -> int:
    return 0


if __name__ == "__main__":
    sys.exit(main())
