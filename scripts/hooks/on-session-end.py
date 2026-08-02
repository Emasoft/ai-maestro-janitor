#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""SessionEnd hook — the janitor's teardown path (TRDD-TL6NL7MK).

Fires when a session TERMINATES (per-session, unlike the per-TURN Stop hook).
Verified against the installed CLI before building: the `SessionEnd` event name
is present in the 2.1.220 binary (strings probe, 2026-08-02), alongside the
other hook events the janitor already rides.

Exactly TWO side effects, both deliberate and both decided against what already
exists (the card's "decide, do not assume"):

1. **USER-memory mirror sync** — `sync_user_memory_mirror()` otherwise runs only
   at SessionStart, so a session's OWN memory writes reach the uninstall-safe
   mirror a whole session late; an uninstall in that window loses them. Syncing
   at teardown closes the gap. The SessionStart call STAYS (it owns the RESTORE
   direction, which must happen at start); this one is the cheap steady-state
   refresh. Same THIN-harness gate as SessionStart: a harness (#J) session never
   writes outside the project.
2. **`session-clean-exit.ts` stamp** — a breadcrumb the fleet diagnostics can
   use to tell "this session ENDED cleanly at T" from "this session DIED"
   (fleet_scan/diagnose_root today cannot distinguish the two).

What it deliberately does NOT do:
- **Never clears `rate-limited.flag` / `resume-after-compact.flag`** — those are
  PROJECT-scoped, not session-scoped, and they are the cross-session resume
  mechanism: the NEXT session's heartbeat consumes them and resumes the pending
  work. Clearing them at teardown would strand every resume that spans a
  restart. (`orphaned-resume-flag` watches for the genuinely orphaned ones.)
- **No state cleanup sweeps** — the purge detectors (reports-purge,
  trashcan-purge, seen-file caps) already own that; a duplicate here would be
  a second writer.
- **No stdout / additionalContext** (TRDD-K1RJUYGK's injection-budget rule) —
  the session is terminating, so there is no context to inject into anyway;
  side effects + stderr diagnostics only, the on-stop-failure shape.

Fail-open everywhere: a teardown fault must never turn a clean exit into an
error exit.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))


def main() -> int:
    # Read stdin only to drain the hook payload (CC writes JSON; an unread pipe
    # is harmless but drain it anyway). The payload is not needed: both side
    # effects are unconditional, and parsing it would add a failure mode.
    try:
        sys.stdin.read()
    except Exception:  # noqa: BLE001 -- fail-open: payload is not load-bearing
        pass

    try:
        import harness_backend  # noqa: PLC0415 -- sibling lib via the path insert
        import state  # noqa: PLC0415

        # Breadcrumb FIRST — the cheapest write, and the one fleet diagnostics
        # read; the mirror sync below may legitimately take longer.
        state.atomic_write(state.state_dir() / "session-clean-exit.ts", str(int(time.time())))

        # Mirror sync — same gate as SessionStart: a THIN-harness (#J) session
        # never writes outside the project (the server owns user-scope chores).
        if not harness_backend.is_harness_session():
            import memory_scopes  # noqa: PLC0415

            synced = memory_scopes.sync_user_memory_mirror()
            if synced:
                state.log_line("session-end", f"user-memory mirror: {synced}")
    except Exception as exc:  # noqa: BLE001 -- teardown must never break the exit
        print(f"[on-session-end] non-fatal: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    # Bare main() (never sys.exit(main())) — the exit code must be 0 even if a
    # future edit makes main() return non-zero by accident; a SessionEnd hook
    # has nothing to veto.
    main()
