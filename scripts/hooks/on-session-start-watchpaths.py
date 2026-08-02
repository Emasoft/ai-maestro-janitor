#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""SessionStart hook (watchPaths declaration only) — arms the FileChanged watch
(TRDD-MN7ZU3RY).

A SEPARATE third SessionStart entry, deliberately: the sibling ``on-session-start.py``
emits PLAIN TEXT (context-injected as-is), and a hook whose stdout must be parsed as
structured JSON cannot share a script with one that prints prose. This one emits EXACTLY
one JSON object or NOTHING:

    {"hookSpecificOutput": {"hookEventName": "SessionStart",
                            "watchPaths": ["<abs>/.gitignore", "<abs>/.mcp.json"]}}

The placement is verified against the INSTALLED CC 2.1.220 binary, not the docs: the
reader is ``hookSpecificOutput.watchPaths`` ("array of absolute paths ... to register
with the FileChanged watcher" — the binary's own description strings), so a top-level
``watchPaths`` key would be silently ignored — exactly the card's trap #2 failure mode.

Proof-of-armed contract: the declaration is also stamped to
``.janitor/state/watch-paths-declared.json`` ({paths, ts}). ``on-file-changed.py``
stamps ``watch-paths-observed.ts`` on every delivered event, and the tracked-ignored
detector cross-checks the pair — a ``.gitignore`` drift found by POLL while the watch
was declared-before-the-change and silent is shouted as a dead watch. Without that
cross-check "declared but never observed" is unfalsifiable (the file may simply never
have changed).

watchPaths carries NO context (TRDD-K1RJUYGK untouched). On ANY error: print NOTHING
(a SessionStart hook's non-JSON stdout would be injected as context) and exit 0.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

_WATCH_BASENAMES = (".gitignore", ".mcp.json")


def main() -> int:
    try:
        sys.stdin.read()  # drain the payload; the declaration is unconditional
    except Exception:  # noqa: BLE001 -- fail-open
        pass
    try:
        import state  # noqa: PLC0415 -- sibling lib via the path insert

        root = state.project_root()
        paths = [str(root / b) for b in _WATCH_BASENAMES]
        state.atomic_write(
            state.state_dir() / "watch-paths-declared.json",
            json.dumps({"paths": paths, "ts": int(time.time())}, separators=(",", ":")),
        )
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "SessionStart",
                        "watchPaths": paths,
                    }
                },
                separators=(",", ":"),
            )
        )
    except Exception as exc:  # noqa: BLE001 -- print NOTHING on error (stdout is context)
        print(f"[on-session-start-watchpaths] non-fatal: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    main()
