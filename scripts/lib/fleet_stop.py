"""Daemon-driven fleet disarm/pause POLICY (TRDD-ME8V2YJF, component A) — the PURE
decisions the daemon uses to type a STOP command into every OTHER running janitor
session when the machine-wide disarm (kill-switch) or pause flag is set.

The daemon already reaches every session for FREEZE recovery (``fleet_scan`` +
``fleet_inject`` + ``terminal_trigger``). This module points that same, already-safe
machinery at the disarm/pause case, so a global ``/janitor-global-disarm`` /
``/janitor-global-pause`` reaches even the ~20 ALREADY-armed sessions whose baked-in
cron prompt predates the self-disarm marker (TRDD-RQ9FIFX6) — with NO human present.

SAFETY (mirrors ``fleet_restart``'s three-gate model):

1. **DEFAULT-OFF.** ``fleet_stop_enabled()`` is false unless the user opts in with
   ``CLAUDE_PLUGIN_OPTION_FLEET_STOP_ENABLED=1``. Typing a slash command into another
   session's pane is a powerful capability, so it ships INERT — the daemon builds the
   plans but fires nothing until the user deliberately enables it.
2. **NEVER the user's live session / the guardian.** ``is_injectable`` refuses this
   process, the daemon, a non-``claude`` pid, and any session the daemon flags as the
   user's active interactive pane (typing keystrokes there would disrupt the human).
3. **DEDUPE.** One injection per ``(pid, flag_state)``; the daemon persists the stamps
   (``global_state``) and passes the seen set in, so a flag that stays set does not
   re-inject every beat.

PURE: every function here is I/O-free and unit-tested. The daemon does the scan, the
persistence, and the fire — this module only DECIDES.
"""

from __future__ import annotations

import os
from collections.abc import Iterable

# flag_state -> the LOCAL slash command the daemon types into each session's pane.
#   disarm => /janitor-disarm  (DELETES the session's heartbeat cron — the true stop,
#             so an already-armed session actually stops firing; TRDD-RQ9FIFX6).
#   pause  => /janitor-pause    (in-place suspend — the cron stays, chores skip).
_FLAG_COMMAND = {"disarm": "/janitor-disarm", "pause": "/janitor-pause"}


def fleet_stop_enabled() -> bool:
    """Master opt-in for daemon-driven fleet-stop injection. DEFAULT-OFF — mirrors
    ``fleet_restart.hard_restart_enabled``. Typing into another session's pane is a
    powerful capability, so it stays dormant until the user sets
    ``CLAUDE_PLUGIN_OPTION_FLEET_STOP_ENABLED=1`` (the documented true spellings)."""
    raw = os.environ.get("CLAUDE_PLUGIN_OPTION_FLEET_STOP_ENABLED", "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


def stop_command_for(flag_state: str | None) -> str | None:
    """The local slash-command to inject for a fleet flag state, or None when the flag
    is not a stop flag (unknown / None). ``disarm`` dominates ``pause`` — that
    precedence is resolved upstream in ``global_state.fleet_stop_flag_state``; here we
    only map an already-decided single state to its command."""
    if not flag_state:
        return None
    return _FLAG_COMMAND.get(flag_state)


def injection_stamp_key(pid: int, flag_state: str) -> str:
    """The stable dedupe key for one ``(session pid, flag-state)`` injection. The
    daemon persists these so a flag that remains set does not re-inject every beat."""
    return f"{pid}:{flag_state}"


def is_injectable(
    *,
    pid: int,
    command: str,
    self_pid: int,
    daemon_pid: int | None,
    is_user_active: bool,
) -> bool:
    """True ONLY when it is safe to type a stop command into this session's pane:

    - ``pid > 0`` and is neither this process nor the daemon — never stop the guardian
      that is doing the stopping (belt-and-suspenders with the daemon excluding itself),
    - ``command`` is a real ``claude`` process — never a pid that merely shares a number,
    - NOT the user's live interactive session — injecting keystrokes into the pane a
      human is typing in would disrupt them; this is the STATE invariant
      ("never touches the user's own interactive session"). The daemon computes
      ``is_user_active`` from its user-presence / transcript-advancing signal; this is
      the independent second gate.
    """
    if pid <= 0 or pid == self_pid or (daemon_pid is not None and pid == daemon_pid):
        return False
    if "claude" not in (command or "").lower():
        return False
    if is_user_active:
        return False
    return True


def select_stop_targets(
    sessions: Iterable[dict],
    *,
    flag_state: str | None,
    self_pid: int,
    daemon_pid: int | None,
    already_injected: set[str],
    user_active_pids: set[int],
) -> list[dict]:
    """PURE. Given the scanned fleet + the current flag state, return one injection
    plan per OTHER session that should be stopped and has not already been.

    ``sessions`` — dicts ``{"pid": int, "command": str, "terminal": dict}`` (the daemon
    adapts each ``fleet_scan.Instance`` into this shape; keeping the input a plain dict
    keeps this policy decoupled and trivially testable).
    ``already_injected`` — dedupe keys already fired (daemon-persisted via ``global_state``).
    ``user_active_pids`` — pids of live user sessions to never disrupt.

    Returns ``[{"pid", "terminal", "command", "flag_state", "dedupe_key"}, ...]`` — the
    daemon fires each via ``fleet_inject`` (iTerm/tmux/ai-maestro) then stamps its key.
    """
    command = stop_command_for(flag_state)
    if command is None or flag_state is None:
        return []
    plans: list[dict] = []
    for sess in sessions:
        pid = int(sess.get("pid", 0) or 0)
        cmd = str(sess.get("command", "") or "")
        if sess.get("server_owned"):
            # An ai-maestro harness agent a LIVE server owns (TRDD-PZLVT2RN): the
            # machine-wide janitor stop is the STANDALONE fleet's stop — harness agents
            # receive their global control from the SERVER (its in-process control ops),
            # so injecting a /janitor-disarm here would have the wrong principal driving
            # them AND mint a disarmed.flag the server's own control model knows nothing
            # about. Skipped BEFORE is_injectable so no dedupe stamp is burned — if the
            # server disappears for good, the operator's adoption override lets a LATER
            # beat inject fresh.
            continue
        terminal = sess.get("terminal", {}) or {}
        has_esc_channel = bool(
            str(terminal.get("tmux_pane", "")).strip()
            or str(terminal.get("iterm_session_id", "")).strip()
        )
        if str(sess.get("diagnosis", "")) == "frozen" and not has_esc_channel:
            # AM8JD9SG F2 — delivery honesty, NARROW case: a frozen target normally gets
            # the stop HARD (ESC breaks the freeze, then the command runs — the
            # test_frozen_target_is_hard contract). But when the ONLY reachable channel
            # is the ai-maestro CLI (no tmux pane, no iTerm id), there is no ESC
            # primitive: the send merely ENQUEUES into a queue that is, by definition,
            # not draining — stamping that "delivered" would silence retries while the
            # stop never takes effect. Skip WITHOUT burning the dedupe stamp; the
            # liveness recovery owns unfreezing, and the first beat that sees the
            # session un-frozen injects the stop for real.
            continue
        if not is_injectable(
            pid=pid,
            command=cmd,
            self_pid=self_pid,
            daemon_pid=daemon_pid,
            is_user_active=pid in user_active_pids,
        ):
            continue
        key = injection_stamp_key(pid, flag_state)
        if key in already_injected:
            continue
        plans.append(
            {
                "pid": pid,
                "terminal": sess.get("terminal", {}),
                "command": command,
                "flag_state": flag_state,
                "dedupe_key": key,
            }
        )
    return plans
