"""Fleet recovery injector (TRDD-324223a6, GROUP A / A3) — the ACTUATION layer.

``session_liveness.diagnose_instance`` says WHAT is wrong and which recovery to
run; ``fleet_scan`` resolves WHERE (the terminal). This module is HOW: it builds
the exact keystroke payload to inject a recovery command into ANOTHER instance's
terminal, choosing the channel from the RESOLVED terminal identity (never this
process's own env) — so the daemon can rescue a session it does not live in.

Four channels, layered so the most-direct/reliable one wins (TRDD-ME8V2YJF follow-up
adds the last two; iTerm/tmux are unchanged):

- **iTerm** → an osascript that targets ONLY the session whose ``id`` equals the
  stored UUID, sends ESC (interrupt the dead/stuck turn), then types the command.
  Generalized from ``compact_trigger._build_osascript`` (which self-targets via
  ``$ITERM_SESSION_ID``) so it can target an arbitrary pane by its stored UUID.
- **tmux** → ``tmux send-keys`` steps (ESC, settle, the literal command, Enter),
  reusing ``terminal_trigger.build_tmux_steps``. tmux is preferred when present:
  an ai-maestro agent pane is automatable directly — no AppleScript, no focus
  steal — which is why this is the ai-maestro-compatible path.
- **ai-maestro CLI** → ``aimaestro-agent.sh session command <tmux-session>
  --newline -- <command>`` (``aimaestro_command_argv``), for an agent session the
  raw TTY scan couldn't place (e.g. a nested/managed tmux fleet_scan can't see
  directly). ``fleet_scan`` pre-resolves the CLI path and tmux session name once
  per scan (never per-instance); no raw-ESC primitive on this channel.
- **Linux GUI** (wtype/xdotool) → reuses ``terminal_trigger.build_wtype_steps`` /
  ``build_xdotool_steps`` (the same builders self-trigger uses), typing into the
  FOCUSED window — best-effort, last resort, tagged by ``fleet_scan`` only when
  no tmux/iTerm channel resolved.

Everything here is PURE / dry-run-able: build the payload, inspect it, THEN fire.
This module covers only the gentle, command-TYPING rungs (rearm/reload/update).
``esc_nudge`` types no command (ESC only) and the hard-restart rungs
(relaunch/force_restart/resurrect) kill/spawn processes — those live in the
daemon task behind the crash-loop guard, not here.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import terminal_trigger  # noqa: E402  (bare sibling import; lib/ is on sys.path)

# Same injection-safety gate as compact_trigger: a stored session id is only ever
# interpolated into an `osascript -e` string AFTER this hex-UUID check, so a
# tampered registry entry can't smuggle AppleScript into the daemon's own shell.
_UUID_RE = re.compile(r"^[0-9A-Fa-f-]{8,64}$")

# The command-typing rungs → the slash-command each injects. `update` re-arms,
# which re-bakes the rolled stub and picks up the new version. `esc_nudge`
# (ESC only) and the hard-restart rungs are deliberately absent — they don't type a
# command, so action_to_command() returns None and build_injection() declines.
_ACTION_COMMAND = {
    "rearm": "/janitor-arm",
    "reload": "/reload-plugins",
    "update": "/janitor-arm",
}


def action_to_command(action: str) -> str | None:
    """The slash-command a command-typing recovery `action` injects, or None when
    the action types no command (esc_nudge = ESC only; hard-restart rungs = daemon)."""
    return _ACTION_COMMAND.get(action)


def valid_session_id(session_id: str) -> bool:
    """True iff `session_id` is a bare iTerm UUID safe to interpolate into an
    osascript string. `$ITERM_SESSION_ID` is `<tty>:<UUID>`; pass the UUID part."""
    return bool(_UUID_RE.match(session_id.strip()))


def iterm_osascript(
    session_id: str, command: str, *, delay_s: float = 2.0, esc_first: bool = True
) -> str:
    """AppleScript that targets ONLY the iTerm session whose id == `session_id`,
    optionally sends ESC, then types `command` (iTerm's `write text` appends a
    return, so the command submits). Generalized from compact_trigger so the daemon
    can target ANOTHER pane by its stored UUID.

    The caller MUST have passed `session_id` through `valid_session_id()` first —
    this function trusts it (the UUID is the only interpolated-from-state value;
    `command` is a fixed internal literal from `_ACTION_COMMAND`, never user input).
    """
    # TWO ESCs (terminal_trigger.HARD_INTERRUPT_ESC_COUNT): one clears a running tool, one
    # ends the (frozen) turn — else the injected command enqueues behind it.
    esc = ("\n".join(terminal_trigger.iterm_esc_lines()) + "\n") if esc_first else ""
    return (
        f"delay {delay_s}\n"
        'tell application "iTerm2"\n'
        "  repeat with w in windows\n"
        "    repeat with t in tabs of w\n"
        "      repeat with s in sessions of t\n"
        f'        if (id of s) is "{session_id}" then\n'
        "          tell s\n"
        f"{esc}"
        f'            write text "{command}"\n'
        "          end tell\n"
        "        end if\n"
        "      end repeat\n"
        "    end repeat\n"
        "  end repeat\n"
        "end tell\n"
    )


def aimaestro_command_argv(cli: str, session: str, command: str) -> list[str]:
    """argv for ``<cli> session command <session> --newline -- <command>`` — the
    frozen ai-maestro CLI interface (issue #42) that types ``command`` into the
    ai-maestro agent whose tmux session is ``session``. PURE — no resolution, no
    I/O; the caller resolves ``cli`` (``terminal_trigger._resolve_aimaestro_cli``)
    and ``session`` (fleet_scan's ``tag_aimaestro_identity``, via
    ``terminal_trigger.match_agent_tmux``) beforehand — mirroring how
    ``iterm_osascript`` takes an already-validated session id rather than
    discovering it itself. Has no raw-ESC primitive (documented on
    ``terminal_trigger._try_ai_maestro_send``): typing into a mid-turn agent
    ENQUEUES the command regardless of hard/soft intent, so there is no
    ``esc_first`` parameter here. (TRDD-ME8V2YJF follow-up)
    """
    return [cli, "session", "command", session, "--newline", "--", command]


def build_injection(terminal: dict, action: str, *, delay_s: float = 2.0) -> dict | None:
    """Build the keystroke-injection PLAN for a recovery `action` into a resolved
    `terminal` (``{'iterm_session_id'?, 'tmux_pane'?}``). PURE — returns a plan the
    caller fires (or inspects in a dry-run); None when the action types no command
    OR the terminal cannot be safely targeted.

    Plan shapes::

        {'channel': 'tmux',  'command': '<cmd>', 'steps': [[argv], ...]}
        {'channel': 'iterm', 'command': '<cmd>', 'osascript': '<script>'}

    tmux is preferred when a pane is present — it is the ai-maestro-compatible,
    no-AppleScript, no-focus-steal path. iTerm is the fallback, gated on a valid
    UUID so a tampered identity can never reach the osascript sink.
    """
    command = action_to_command(action)
    if command is None:
        return None  # esc_nudge / hard-restart — not a command-typing injection
    pane = terminal.get("tmux_pane", "").strip()
    # Gate the tmux pane exactly as the iTerm UUID is gated below: only a bare `%<n>`
    # may reach the `tmux send-keys -t <pane>` argv. A malformed pane (e.g. a
    # leading `-`, which tmux would read as a FLAG) is rejected, and we fall through
    # to the iTerm channel — mirroring the UUID decline path, so neither sink ever
    # receives an unvalidated identity.
    if pane and terminal_trigger.valid_tmux_pane(pane):
        return {
            "channel": "tmux",
            "command": command,
            "delay_s": delay_s,
            "steps": terminal_trigger.build_tmux_steps(pane, command),
        }
    sid_full = terminal.get("iterm_session_id", "").strip()
    sid = sid_full.split(":")[-1].strip()  # accept '<tty>:<uuid>' or a bare uuid
    if sid and valid_session_id(sid):
        return {
            "channel": "iterm",
            "command": command,
            "delay_s": delay_s,
            "osascript": iterm_osascript(sid, command, delay_s=delay_s),
        }
    return None  # unreachable: no tmux pane and no valid iTerm UUID


def fire(plan: dict | None) -> bool:
    """Fire a built injection plan fully DETACHED — so the daemon never blocks and
    is never killed by the very ESC the plan sends. Returns True iff a sender was
    launched, False otherwise. Safe to call with None (a declined plan) → False.

    A spawn failure (missing `osascript`, a PATH-stripped env, any OSError) returns
    False rather than raising: the caller renders that as a per-instance FIRE-FAILED
    log line, whereas an escaping exception would crash the WHOLE fleet beat through
    Task.run's blanket handler and bump the task toward quarantine — one un-spawnable
    sender must not disable the guardian for every other instance that tick."""
    if not plan:
        return False
    try:
        if plan["channel"] == "iterm":
            subprocess.Popen(  # noqa: S603 - fixed argv, no shell; script is UUID-gated
                ["osascript", "-e", plan["osascript"]],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True
        if plan["channel"] == "tmux":
            # Reuse the proven detached runner — it interprets the RUN/SLEEP step tags
            # and runs them in a base64-encoded detached child, so (a) the tags are
            # honored (NOT exec'd as `RUN`/`SLEEP` commands) and (b) the ESC the steps
            # send can't kill the daemon that launched them.
            terminal_trigger._fire_detached_steps(plan["delay_s"], plan["steps"])
            return True
        if plan["channel"] in ("wtype", "xdotool"):
            # Same detached-child runner as tmux — it interprets the RUN/SLEEP step
            # tags and runs them in a delayed, fully-detached child so the ESC they
            # send can never kill the daemon that launched them (TRDD-ME8V2YJF
            # follow-up: Linux GUI-terminal parity, best-effort focused-window send).
            terminal_trigger._fire_detached_steps(plan["delay_s"], plan["steps"])
            return True
        if plan["channel"] == "aimaestro":
            # Fire-and-forget (unlike self-trigger's _try_ai_maestro_send, which
            # waits synchronously for CLI confirmation): the daemon's fleet-stop
            # beat must never block on a subprocess, so we spawn detached exactly
            # like the iTerm/osascript branch above (TRDD-ME8V2YJF follow-up).
            subprocess.Popen(  # noqa: S603 - fixed argv (resolved CLI + validated session), no shell
                plan["argv"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return True
    except (OSError, subprocess.SubprocessError):
        return False
    return False
