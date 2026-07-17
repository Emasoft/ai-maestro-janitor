#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""oauth-beacon-refresh — keep the live-identity beacon fresh so rotation isn't blinded.

THE BUG (TRDD-6AABK2BG): proactive rotation silently watched the WRONG account, so the user
had to rotate by hand, repeatedly. The live-identity beacon can only be stamped from a context
that can READ the primary credential, and the only automatic one is SessionStart — ONCE per
session. (The daemon's own cmd_tick stamp is a guaranteed no-op: it runs headless, so FIX B2
skips the primary read by design — TRDD-K3WQ7XM9.) A manual /login mid-session therefore left
the beacon FRESH-BUT-WRONG for up to 24h; `_resolve_untrusted_live` matched it against the
equally-stale `-livebak` mirror, "confirmed" the old account, and evaluated ITS usage — always
under the switch threshold — while the real live account burned to its cap.

THE HEARTBEAT IS THE FIX: it runs in the SESSION context (only daemon.py sets
JANITOR_ROTATOR_HEADLESS), which is exactly the context that CAN read the primary and that the
daemon structurally cannot be. So the one component able to refresh the beacon is this one.

CHEAP BY CONSTRUCTION: a NON-prompting attribute read (`mdat`, no `-w`) gates the stamp, so
the steady state costs one metadata call and ZERO `-w` secret reads. Only a real credential
change pays for a stamp. This is deliberate — a `-w` read on a cadence is the ACL prompt flood
that `keychain-health` ("findability only — never -w"), TRDD-EQJPPZ2L and TRDD-K3WQ7XM9 all
exist to prevent, and re-creating it here would be a regression, not a fix.

OPT-IN BY PRESENCE: silent no-op unless a configured rotator home with a state.json exists, so
janitor installs without the rotator pay nothing.

SILENT: a re-stamp is routine maintenance, not drift — it emits NO heartbeat line. A real
live-account CHANGE is recorded durably in rotator.log by refresh_beacon_if_stale itself.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "lib"))
sys.path.insert(0, str(_HERE.parent / "oauth_rotator"))

import rotator  # noqa: E402  # scripts/oauth_rotator/rotator.py
import state  # noqa: E402


def main() -> int:
    if not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_OAUTH_BEACON_REFRESH_ENABLED", True):
        return 0
    # Opt-in by presence, via the same SSOT the daemon + the other rotator detectors use, so
    # this never resolves a different home than the code that READS the beacon.
    if rotator.configured_rotator_home() is None:
        return 0
    try:
        rotator.refresh_beacon_if_stale()
    except Exception as exc:  # noqa: BLE001 -- a beacon refresh must never break a heartbeat
        state.log_line("oauth-beacon-refresh", f"beacon refresh skipped: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
