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


def main() -> int:
    # All side-effecting code lives inside main() so the hook script is
    # safely importable (no module-scope sys.exit). This hook no longer
    # imports the `state` library — the previous last-activity write
    # was dead code (no detector consumed it). The hook intentionally
    # does NOT clear `rate-limited.flag` either; that belongs to the
    # heartbeat itself, since a successful turn after a rate-limit is
    # exactly the signal that triggers the [janitor-resume] emission on
    # the next fire. The CLAUDE_PLUGIN_ROOT guard is kept as a stub for
    # future stop-driven behaviour.
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
    if not plugin_root:
        print("[on-stop] CLAUDE_PLUGIN_ROOT unset; skipping", file=sys.stderr)
        return 0
    return 0


if __name__ == "__main__":
    # Bare main() — see on-stop-failure.py for the rationale.
    main()
