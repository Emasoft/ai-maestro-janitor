#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""UserPromptSubmit hook — Python port of on-prompt-submit.sh.

Fires when the user types a prompt. Currently a no-op: the previous
implementation refreshed a `last-activity.ts` timestamp, but no
detector ever reads it (the heartbeat doesn't gate on user activity).
The hook is kept registered so reintroducing prompt-submit-driven
behaviour later doesn't require a settings.json edit.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_PLUGIN_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
if not _PLUGIN_ROOT:
    print("[on-prompt-submit] CLAUDE_PLUGIN_ROOT unset; skipping", file=sys.stderr)
    sys.exit(0)

sys.path.insert(0, str(Path(_PLUGIN_ROOT) / "scripts" / "lib"))


def main() -> int:
    return 0


if __name__ == "__main__":
    sys.exit(main())
