#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Decide whether a disarm may record `disarmed.flag` — the "the USER opted out" claim.

Backing script for `/janitor-disarm` step 3 (TRDD-RDFWQIFA).

**Why a guard is needed at all.** `disarmed.flag` does not merely stop the heartbeat — it tells the
FLEET GUARDIAN that a human deliberately stopped it, so the project becomes *sacrosanct* and is never
re-armed (`fleet_scan.deliberately_unarmed` → `session_liveness` → `daemon`), and it also suppresses
the SessionStart re-arm nudge. It is the OFF switch for both of the heartbeat's survival paths.

The skill wrote it unconditionally. So an agent that ran `/janitor-disarm` on its own judgment forged
a human decision and permanently disabled the one mechanism designed to undo its mistake. That is not
hypothetical: on 2026-07-14 an agent disarmed to save tokens during a rate limit, and the session sat
dead for HOURS — the exact stall the heartbeat exists to abolish.

**The fix is provenance, not prohibition.** The cron is still deleted either way — a disarm always
stops *this* session's heartbeat immediately. What requires authority is the *claim that a human chose
it*, because that claim is what disables the guardian. Absent authority we simply do not make the
claim, and the guardian re-arms within a beat. An agent-initiated disarm becomes SELF-HEALING instead
of permanent.

Two things count as authority, and an agent can fabricate neither:

1. A fresh `user_intent` token for `disarm`, stamped by the UserPromptSubmit hook from the user's RAW
   keystrokes. The model never gets to author a UserPromptSubmit payload.
2. A genuine machine-wide stop flag (`kill_switch` / `global_pause`). This is the `[janitor-self-disarm]`
   path: the user already stopped the whole fleet, and each session disarming its own cron is how that
   stop is *executed* (a cron fire is a billed turn even when it does nothing — TRDD-RQ9FIFX6). The
   authority is real global state, and the flag that sets it is itself intent-gated in
   `global_control_cli`, so the chain has no forgeable link.

Prints exactly one token:
  DISARM_RECORDED:<reason>   — the flag was written; the guardian will honor the opt-out.
  DISARM_UNVERIFIED          — no authority; the flag was NOT written. Tell the user that the
                               heartbeat stopped for now, and that typing `/janitor-disarm`
                               themselves is what makes it stick.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "lib"))

import global_state as gs  # noqa: E402
import state  # noqa: E402
import user_intent  # noqa: E402


def authority() -> str | None:
    """Why this disarm may claim the user chose it — or None when it may not."""
    if user_intent.intent_fresh("disarm"):
        user_intent.consume_intent("disarm")
        return "user-asked"
    # The machine-wide stop is executed by every session disarming its own cron. Read the REAL global
    # state; fail CLOSED (treat an unreadable flag as absent) so a broken read can never invent
    # authority that does not exist.
    try:
        if gs.kill_switch_present():
            return "global-stop"
    except OSError:
        pass
    return None


def main() -> int:
    why = authority()
    if why is None:
        print("DISARM_UNVERIFIED")
        return 0
    flag = state.state_dir() / state.DISARMED_FLAG
    try:
        state.init_state()
        state.atomic_write(flag, str(int(time.time())))
    except OSError as e:
        print(f"DISARM_UNVERIFIED (could not write the flag: {e})")
        return 0
    # Clear the persistent, machine-global "armed forever" claim (TRDD-TUIBWHT7) whenever a
    # disarm is actually recorded — both authorities above (a fresh user `disarm` intent, or the
    # machine-wide kill-switch already being set) are exactly the two things the card names as
    # allowed to clear it. Best-effort: a disarm must still succeed even if this write fails.
    try:
        gs.clear_armed()
    except OSError:
        pass
    print(f"DISARM_RECORDED:{why}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
