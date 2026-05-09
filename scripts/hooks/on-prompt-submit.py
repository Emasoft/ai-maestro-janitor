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


def main() -> int:
    # All side-effecting code lives inside main() so the hook script is
    # safely importable (no module-scope sys.exit). This hook no longer
    # imports the `state` library — the previous last-activity write was
    # dead code (no detector consumed it). The CLAUDE_PLUGIN_ROOT guard
    # is kept as a stub for future prompt-submit-driven behaviour.
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
    if not plugin_root:
        print(
            "[on-prompt-submit] CLAUDE_PLUGIN_ROOT unset; skipping",
            file=sys.stderr,
        )
        return 0
    return 0


if __name__ == "__main__":
    # Bare main() — see on-stop-failure.py for the rationale.
    main()
