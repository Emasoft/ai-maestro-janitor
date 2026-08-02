#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""ConfigChange hook — event-driven fast path for the config scope-drift detectors
(TRDD-MN7ZU3RY).

Verified against the INSTALLED CC 2.1.220 binary (zod schema, strings probe): payload is
``{hook_event_name: "ConfigChange", source: enum[user_settings, project_settings,
local_settings, policy_settings, skills], file_path?: string}``; the hook matcher matches
``source``. The enum has NO MCP member, so `.mcp.json` changes ride the FileChanged watch
instead (`on-file-changed.py`).

THE PRIMITIVE IS MARK-DUE, NOT RUN (advisor verdict 2026-08-02): unlink the mapped
detectors' ``last-run-<name>.ts`` stamps so the NEXT heartbeat fire runs them immediately
(``_detector_is_due`` treats a missing stamp as due — dispatch.py). Having the hook RUN a
detector and swallow its stdout would CONSUME the finding: ``dedupe.emit_once`` records
the seen-key, and the next heartbeat then stays silent. Mark-due has no second
finding-writer and no consumed findings; the poll remains the backstop for every project
without a live session (the card's trap #1).

DELIBERATELY NO LOCK: dispatch's Phase-2 loop takes no ``detector_lock`` (verified — zero
uses in dispatch.py; that lock is the daemon-vs-cron MF3 discipline), so holding it here
would serialize nothing, and "skip when busy" would silently DROP the event. A bare
``unlink`` is atomic against ``atomic_write``'s ``os.replace``.

KNOWN, ACCEPTED lost-wakeup window: an event landing WHILE the mapped detector is
mid-run gets its unlink overwritten by ``_mark_detector_ran`` at run END — bounded by the
120s detector timeout and healed by the poll backstop at the detector's own cadence.

Zero stdout ever (a ConfigChange hook's stdout would be context-shaped — TRDD-K1RJUYGK),
always exit 0: an event hook must never break the session over telemetry.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

# Any config source can move settings-scope material, and settings files also carry
# MCP-adjacent config (enabledPlugins, mcp servers in settings) — so both detectors go
# due on any ConfigChange. A spurious due-run costs one bounded one-shot.
_MARK_DUE = ("settings-scope-drift", "mcp-config-drift")


def main() -> int:
    try:
        sys.stdin.read()  # drain; the payload is not load-bearing (any source ⇒ same marks)
    except Exception:  # noqa: BLE001 -- fail-open
        pass
    try:
        import state  # noqa: PLC0415 -- sibling lib via the path insert

        for name in _MARK_DUE:
            (state.state_dir() / f"last-run-{name}.ts").unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001 -- telemetry only; never break the session
        print(f"[on-config-change] non-fatal: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    main()
