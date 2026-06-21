"""Fleet recovery injector (TRDD-324223a6, GROUP A / A3) — the ACTUATION layer.

``session_liveness.diagnose_instance`` says WHAT is wrong and which recovery to
run; ``fleet_scan`` resolves WHERE (the terminal). This module is HOW: it builds
the exact keystroke payload to inject a recovery command into ANOTHER instance's
terminal, choosing the channel from the RESOLVED terminal identity (never this
process's own env) — so the daemon can rescue a session it does not live in.

Two channels, both already proven elsewhere in the plugin:

- **iTerm** → an osascript that targets ONLY the session whose ``id`` equals the
  stored UUID, sends ESC (interrupt the dead/stuck turn), then types the command.
  Generalized from ``compact_trigger._build_osascript`` (which self-targets via
  ``$ITERM_SESSION_ID``) so it can target an arbitrary pane by its stored UUID.
- **tmux** → ``tmux send-keys`` steps (ESC, settle, the literal command, Enter),
  reusing ``terminal_trigger.build_tmux_steps``. tmux is preferred when present:
  an ai-maestro agent pane is automatable directly — no AppleScript, no focus
  steal — which is why this is the ai-maestro-compatible path.

Everything here is PURE / dry-run-able: build the payload, inspect it, THEN fire.
This module covers only the gentle, command-TYPING rungs (rearm/reload/update).
``esc_nudge`` types no command (ESC only) and the nuclear rungs
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
# (ESC only) and the nuclear rungs are deliberately absent — they don't type a
# command, so action_to_command() returns None and build_injection() declines.
_ACTION_COMMAND = {
    "rearm": "/janitor-arm",
    "reload": "/reload-plugins",
    "update": "/janitor-arm",
}


def action_to_command(action: str) -> str | None:
    """The slash-command a command-typing recovery `action` injects, or None when
    the action types no command (esc_nudge = ESC only; nuclear rungs = daemon)."""
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
    esc = (
        "            write text (character id 27) without newline\n"
        "            delay 0.6\n"
    ) if esc_first else ""
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
        return None  # esc_nudge / nuclear — not a command-typing injection
    pane = terminal.get("tmux_pane", "").strip()
    if pane:
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
    launched. Safe to call with None (a declined plan) → returns False."""
    if not plan:
        return False
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
    return False
