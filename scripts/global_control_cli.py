#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Backing CLI for the MACHINE-WIDE janitor control flags (TRDD-a3fa4d5d).

Thin wrapper over global_state's two distinct global flags, so each flag path has
ONE source of truth (never duplicated into a skill's bash):

    global_control_cli.py disarm [reason]   # /janitor-global-disarm — TRUE STOP
    global_control_cli.py arm                # /janitor-global-arm    — revive after a disarm
    global_control_cli.py reload-skills [reason]  # /janitor-global-reload-skills — fleet skills reload
    global_control_cli.py status             # show the active flag

PAUSE AND MAINTENANCE ARE GONE (owner directive 2026-07-31, *"remove the very option of
disabling the janitor features"*). Both left the daemon resident and every heartbeat firing
while doing none of the work, which from the outside — a process list, a cron list, a daemon
heartbeat — is indistinguishable from a healthy fleet; that is exactly how a project sat
silently disabled for two weeks. `arm` still SWEEPS both retired flags so an older version
cannot leave a machine looking suspended, and BOTH verbs are REJECTED rather than accepted as
no-ops: a retired verb that exits 0 lets a caller keep believing the fleet is quiesced.

ONE machine-wide mechanism remains: DISARM, the TRUE STOP. The running daemon EXITS on its
next loop, per-session heartbeats stop re-spawning it, AND every session's heartbeat goes
SILENT. It is loud and total — the cron is deleted, so a disarmed session cannot be mistaken
for a working one. Revive = `arm`. Cost pressure is answered per-session by the dynamic
cadence tier (fewer fires, same work) and by a drift line naming the spend.

`status` is the safe read-only default. Exits 0 on success; prints a one-line result.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import global_state as gs  # noqa: E402  (bare sibling import; lib/ is on sys.path)
import user_intent  # noqa: E402


def _status_line() -> str:
    # One state to report, because there is one machine-wide switch. The MAINTENANCE branch
    # that used to precede this — and its "MAINTENANCE + DISARMED" combination, which existed
    # only because the two flags could disagree about whether the daemon was stopped or merely
    # idle — went with the mode (owner directive 2026-07-31).
    if gs.kill_switch_present():
        return "DISARMED (kill-switch set — daemon stopped AND every per-session heartbeat silent; run /janitor-global-arm to revive)"
    return "RUNNING (no global stop)"


# The machine-wide STOPS. These are the only sub-commands that need human authority: each one halts
# the janitor across EVERY project on this machine, and `disarm` additionally makes every session
# self-disarm its own cron (the `[janitor-self-disarm]` path). The revive (`arm`) is deliberately
# NOT gated — restoring a safety system must never be harder than stopping it.
_STOP_COMMANDS = {"disarm": "global-disarm"}


def _authorized(cmd: str) -> bool:
    """True iff the USER asked for this stop (TRDD-RDFWQIFA).

    Without this, the disarm guard on `disarmed.flag` would have a trivial bypass: an agent could set
    the machine-wide stop itself, and every session would then dutifully self-disarm ON that stop's
    authority. Gating the stop closes the chain, so there is no forgeable link anywhere in it.

    The token is minted by the UserPromptSubmit hook from the user's RAW keystrokes — the one surface
    an agent can never author. Fails CLOSED: no token, no stop.
    """
    verb = _STOP_COMMANDS.get(cmd)
    if verb is None:
        return True  # not a stop — nothing to authorize
    if user_intent.intent_fresh(verb):
        user_intent.consume_intent(verb)
        return True
    return False


def main() -> int:
    argv = sys.argv[1:]
    cmd = argv[0] if argv else "status"
    reason = " ".join(argv[1:]) if len(argv) > 1 else ""
    if not _authorized(cmd):
        print(
            f"REFUSED: `{cmd}` stops the janitor on EVERY project on this machine, so it needs the "
            f"user's own request. No recent user instruction asked for it.\n"
            f"If you are the user: type /janitor-global-{cmd} yourself and it will run.\n"
            f"(Agents: a budget/rate-limit problem is answered by a slower cadence, which fires "
            f"less often and still does the work — never by a stop.)"
        )
        return 1
    if cmd == "disarm":
        # DISARM is the TRUE STOP. The kill-switch makes the daemon EXIT, and the
        # kill-switch-honoring dispatch.py (TRDD-NJ22HNC3) silences every heartbeat
        # directly. This used to ALSO raise the global-pause flag as belt-and-braces for
        # pre-fix cached dispatchers; the pause flag is retired, and the versions that
        # needed that fallback are long past their cache-GC window.
        gs.set_kill_switch(reason)
        print("janitor globally DISARMED — the daemon exits on its next loop, per-session heartbeats will not re-spawn it, AND every session's heartbeat goes silent on its next fire. Run /janitor-global-arm to revive.")
        return 0
    if cmd == "arm":
        # Full revive: clear the kill-switch so the daemon may respawn and heartbeats
        # resume. It also sweeps the RETIRED global-pause flag, which older versions
        # could have left set — nothing reads it now, but a stale flag in the control
        # plane makes a healthy machine look suspended to the next reader.
        #
        # janitor#77 item 1: this clears machine-wide FLAGS only — it creates no
        # cron, anywhere. A project whose heartbeat cron never existed (or already
        # died) stays exactly that way after this call; only /janitor-arm, run inside
        # that project's own session, creates its cron. Say so in the printed output
        # itself (not just the skill doc) so a user reading just the CLI's own line
        # cannot mistake this for a fleet-wide arm.
        gs.clear_kill_switch()
        gs.clear_global_pause()
        gs.clear_maintenance_mode()
        print(
            "janitor global disarm cleared — the daemon may be (re)spawned again and "
            "already-armed per-session heartbeats resume. This does NOT arm any "
            "per-project heartbeat cron: a project with no cron (or a dead one) stays "
            "unarmed. Run /janitor-arm inside each project that needs one."
        )
        return 0
    if cmd in ("maintenance", "maintenance-off", "pause", "unpause"):
        # REJECT, never no-op. These verbs are retired (owner directive 2026-07-31), and a
        # retired verb that exits 0 is worse than one that fails: the caller walks away
        # believing the fleet is quiesced — which is the very illusion the mode created.
        # `maintenance-off`/`unpause` are rejected too because there is nothing left to lift;
        # any flag still on disk is inert and is swept by the next arm.
        print(
            f"REFUSED: `{cmd}` no longer exists. Maintenance mode and pause were removed because "
            f"they left the daemon resident and every heartbeat firing while doing no work, so a "
            f"quiesced fleet was indistinguishable from a healthy one. To spend less, slow a "
            f"project's cadence (CLAUDE_PLUGIN_OPTION_HEARTBEAT_CRON_SLOW). To actually stop: "
            f"/janitor-global-disarm (machine-wide) or /janitor-disarm (this project) — both "
            f"delete the cron, so a stopped session cannot be mistaken for a working one."
        )
        return 1
    if cmd == "reload-skills":
        # FLEET standalone-skills reload. Stamp the machine-wide generation; each live
        # session's heartbeat emits [janitor-reload-skills] once (per-project ack) on its
        # next fire, which runs /janitor-reload-skills → /reload-skills locally. Unlike
        # disarm this is a MONOTONIC generation, never a persistent stop-state — it
        # requests a one-time reload, not an ongoing posture. Rollout caveat (mirrors the
        # [janitor-reload] path): a heartbeat whose cron prompt was baked BEFORE this
        # marker shipped won't act on it until the session re-arms.
        gs.set_skills_reload_flag(reason)
        print("janitor global reload-skills requested — every live session's next heartbeat will emit [janitor-reload-skills] once and run /reload-skills locally, so newly installed STANDALONE skills/commands load fleet-wide. (Already-armed sessions honor the new marker only after a re-arm.)")
        return 0
    if cmd == "status":
        print(_status_line())
        return 0
    sys.exit(f"unknown command: {cmd!r} (use: disarm [reason] | arm | reload-skills [reason] | status)")


if __name__ == "__main__":
    sys.exit(main())
