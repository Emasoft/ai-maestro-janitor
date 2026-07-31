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
    global_control_cli.py maintenance [reason]    # /janitor-global-maintenance — cache-warm cheap fires
    global_control_cli.py maintenance-off         # /janitor-global-maintenance-off — resume full mode
    global_control_cli.py status             # show the active flag

PAUSE IS GONE (owner directive 2026-07-31, *"remove the very option of disabling the
janitor features"*). A stop that leaves the daemon resident and every heartbeat firing
but doing nothing is, from the outside, indistinguishable from a healthy fleet — which is
exactly how a project sat silently disabled for two weeks. `arm` still SWEEPS the retired
flag so an older version cannot leave a machine looking suspended.

Two mechanisms remain, deliberately distinct:
  * DISARM = the TRUE STOP. The running daemon EXITS on its next loop, per-session
    heartbeats stop re-spawning it, AND every session's heartbeat goes SILENT. It is
    loud and total — the cron is deleted, so a disarmed session cannot be mistaken for a
    working one. Revive = `arm`.
  * MAINTENANCE = the maintenance flag (TRDD-FPL60EKV). Unlike disarm, sessions
    KEEP firing — but each fire is cache-refresh-ONLY (no detectors, no daemon tasks). The
    daemon idles its workloads. This keeps every project's prompt cache warm at the 0.1x
    cache-READ rate (~1/10 the 1.0x REWRITE a dead cache costs on the next real turn), so
    it is the cheap alternative to disarm when the fleet is idle-but-returning. Revive =
    `maintenance-off`.

`status` is the safe read-only default. Exits 0 on success; prints a one-line result.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import global_state as gs  # noqa: E402  (bare sibling import; lib/ is on sys.path)
import user_intent  # noqa: E402


def _status_line() -> str:
    # Precedence mirrors dispatch's mode resolution: MAINTENANCE wins over a stop for SESSIONS
    # (they keep firing cache-refresh-only) — a maintenance fire is an explicit keep-warm
    # intent (TRDD-FPL60EKV). But the DAEMON checks the kill-switch FIRST and EXITS, so when
    # BOTH maintenance and the kill-switch are set the daemon is stopped, not idle — report
    # that honestly (/code-review B6) instead of claiming "daemon idle".
    if gs.maintenance_mode_present():
        if gs.kill_switch_present():
            return "MAINTENANCE + DISARMED (sessions still fire cache-refresh-only, but the kill-switch stopped the daemon; run /janitor-global-arm, then /janitor-global-maintenance-off, to fully resume)"
        return "MAINTENANCE (heartbeats stay armed but fire cache-refresh-only — no detectors, daemon idle; run /janitor-global-maintenance-off to resume full mode)"
    if gs.kill_switch_present():
        return "DISARMED (kill-switch set — daemon stopped AND every per-session heartbeat silent; run /janitor-global-arm to revive)"
    return "RUNNING (no global stop or maintenance)"


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
            f"(Agents: a budget/rate-limit problem is answered by /janitor-global-maintenance — "
            f"which keeps firing cheaply and keeps nudging — never by a stop.)"
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
        print(
            "janitor global disarm cleared — the daemon may be (re)spawned again and "
            "already-armed per-session heartbeats resume. This does NOT arm any "
            "per-project heartbeat cron: a project with no cron (or a dead one) stays "
            "unarmed. Run /janitor-arm inside each project that needs one."
        )
        return 0
    if cmd == "maintenance":
        # MAINTENANCE (TRDD-FPL60EKV): sessions stay ARMED and keep firing, but each fire is
        # cache-refresh-only (dispatch resolves mode=maintenance → no detectors, no daemon
        # spawn), and the daemon idles its task workloads. The cheap way to keep every
        # project's prompt cache warm (0.1x read) instead of letting it die (1.0x rewrite).
        gs.set_maintenance_mode(reason)
        print("janitor globally in MAINTENANCE mode — every session's heartbeat stays ARMED but fires cache-refresh-only (no detectors, no daemon tasks), keeping every project's prompt cache warm at ~1/10 the cost of letting it die. Run /janitor-global-maintenance-off to resume full mode.")
        return 0
    if cmd == "maintenance-off":
        gs.clear_maintenance_mode()
        print("janitor global maintenance lifted — heartbeats resume FULL fires (detectors) and the daemon resumes its task workloads.")
        return 0
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
    sys.exit(f"unknown command: {cmd!r} (use: disarm [reason] | arm | maintenance [reason] | maintenance-off | reload-skills [reason] | status)")


if __name__ == "__main__":
    sys.exit(main())
