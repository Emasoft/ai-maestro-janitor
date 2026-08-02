#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""FileChanged hook — event-driven fast path for the file-watch scope-drift detectors
(TRDD-MN7ZU3RY).

Verified against the INSTALLED CC 2.1.220 binary (zod schema, strings probe): payload is
``{hook_event_name: "FileChanged", file_path: string, event: enum[change, add, unlink]}``;
the hook matcher matches ``basename(file_path)``. The watch list is declared by
``on-session-start-watchpaths.py`` via ``hookSpecificOutput.watchPaths`` (absolute paths).

Same mark-due primitive, same no-lock rationale, same accepted lost-wakeup window as
``on-config-change.py`` — read that docstring; it is the canonical statement.

This hook ALSO stamps ``watch-paths-observed.ts`` on EVERY invocation — the falsifiable
half of the proof-of-armed contract (the card's trap #2): the tracked-ignored detector
cross-checks it and shouts when a ``.gitignore`` drift arrived by POLL although the watch
claimed to be armed (declared before the change, yet no event observed).

Zero stdout ever, always exit 0.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

# basename -> the detectors whose poll answers that file's question.
_MARK_DUE_BY_BASENAME: dict[str, tuple[str, ...]] = {
    ".gitignore": ("tracked-ignored", "project-memory-tracked"),
    ".mcp.json": ("mcp-config-drift",),
}


def main() -> int:
    raw = ""
    try:
        raw = sys.stdin.read()
    except Exception:  # noqa: BLE001 -- fail-open
        pass
    try:
        import state  # noqa: PLC0415 -- sibling lib via the path insert

        # Observed stamp FIRST and unconditionally: it proves the watch DELIVERS,
        # which must not depend on whether this particular file maps to a detector.
        state.atomic_write(
            state.state_dir() / "watch-paths-observed.ts", str(int(time.time()))
        )

        try:
            file_path = str(json.loads(raw).get("file_path", ""))
        except Exception:  # noqa: BLE001 -- malformed payload ⇒ nothing to map
            file_path = ""
        for name in _MARK_DUE_BY_BASENAME.get(Path(file_path).name, ()):
            (state.state_dir() / f"last-run-{name}.ts").unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001 -- telemetry only; never break the session
        print(f"[on-file-changed] non-fatal: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    main()
