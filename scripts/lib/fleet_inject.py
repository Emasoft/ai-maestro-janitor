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
    # --force: a plugin whose code is mid-use can refuse a plain reload and stay
    # on the old cached version (user directive 2026-07-10) — every janitor
    # sender of /reload-plugins forces.
    "reload": "/reload-plugins --force",
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
    this function trusts it.

    `command` is ESCAPED (audit finding 3). It used to be raw f-string-interpolated into
    `write text "…"`, guarded only by the fact that every caller happens to pass a fixed
    internal literal (`/janitor-arm`, `/reload-plugins --force`, `claude --continue`). But
    `build_command_plan` and `fleet_restart.command_injection_plan` both ADVERTISE
    themselves as builders for an "arbitrary"/"raw" command, so a future caller passing
    untrusted text would inject AppleScript on the iTerm channel — and only there, since
    tmux/wtype/xdotool pass argv (or `-l` literal) and are already safe. A `"` or `\\` would
    break the script; a crafted string could append statements. Escape at the sink, so the
    iTerm channel is as safe as the others no matter who calls it.

    The escaping (and the newline refusal) lives in `terminal_trigger.applescript_quote` —
    the SSOT every iTerm `write text` builder shares.
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
        f'            write text "{terminal_trigger.applescript_quote(command)}"\n'
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


def build_command_plan(
    terminal: dict, command: str, *, esc_first: bool = True, delay_s: float = 2.0
) -> dict | None:
    """THE single channel-selection builder: turn a resolved `terminal` identity plus
    an already-chosen `command` into a fire-able plan, or None when no safe channel
    resolves. PURE — no resolution, no I/O; `fleet_scan` populated every key.

    Fallback order — tmux -> iterm -> aimaestro -> linux-gui — is the order
    `fleet_scan.tag_linux_gui_identity` documents, most-direct first. Plan shapes::

        {'channel': 'tmux',     'command': ..., 'delay_s': ..., 'steps': [[argv], ...]}
        {'channel': 'iterm',    'command': ..., 'delay_s': ..., 'osascript': '<script>'}
        {'channel': 'aimaestro','command': ..., 'argv': [cli, 'session', ...]}
        {'channel': 'wtype'|'xdotool', 'command': ..., 'delay_s': ..., 'steps': [...]}

    WHY this lives here and not in `fleet_restart`: both the GENTLE command-typing
    rungs (`build_injection`, below) and the HARD restart rungs
    (`fleet_restart._command_plan`) must reach exactly the same set of instances. They
    did not: this builder used to stop after iterm, while the hard path already walked
    all four. An ai-maestro agent reachable ONLY via the CLI channel — or a Linux GUI
    terminal — was therefore reported UNREACHABLE for a harmless `/janitor-arm`, kept
    escalating, and eventually met a rung that KILLS it. A severity inversion: the
    gentle fix was skipped precisely where the violent one landed. One builder, one
    reachability set, so the two can never drift again.

    Every identity that reaches a sink is validated first (bare `%<n>` tmux pane, hex
    iTerm UUID) — a malformed one declines that channel and falls through rather than
    smuggling a flag into `tmux send-keys` or AppleScript into `osascript`.
    """
    pane = terminal.get("tmux_pane", "").strip()
    if pane and terminal_trigger.valid_tmux_pane(pane):
        # esc_first MUST be honored here too (TRDD-0GPQROC1): a mid-turn Claude in a
        # tmux pane is interrupted by ESC exactly like in iTerm, so the old
        # always-ESC shortcut ("harmless at a shell prompt") silently turned every
        # SOFT intent hard on this channel and killed in-flight work.
        return {
            "channel": "tmux",
            "command": command,
            "delay_s": delay_s,
            "steps": terminal_trigger.build_tmux_steps(pane, command, esc_first=esc_first),
        }
    sid = terminal.get("iterm_session_id", "").strip().split(":")[-1].strip()
    if sid and valid_session_id(sid):  # accept '<tty>:<uuid>' or a bare uuid
        return {
            "channel": "iterm",
            "command": command,
            "delay_s": delay_s,
            "osascript": iterm_osascript(sid, command, delay_s=delay_s, esc_first=esc_first),
        }
    session = terminal.get("aimaestro_session", "").strip()
    cli = terminal.get("aimaestro_cli", "").strip()
    if session and cli:
        # No ESC primitive on this channel (see terminal_trigger._try_ai_maestro_send):
        # typing into a mid-turn agent ENQUEUES regardless, so esc_first is unused. No
        # delay_s either — the CLI is fired directly, not through the delayed step runner.
        return {
            "channel": "aimaestro",
            "command": command,
            "argv": aimaestro_command_argv(cli, session, command),
        }
    gui_channel = terminal.get("linux_gui_channel", "").strip()
    if gui_channel in ("wtype", "xdotool"):
        # esc_first honored here too (TRDD-0GPQROC1) — same reasoning as the tmux
        # channel above: ESC into a mid-turn Claude interrupts it, so soft must
        # genuinely mean soft on every keystroke channel.
        builder = (
            terminal_trigger.build_wtype_steps
            if gui_channel == "wtype"
            else terminal_trigger.build_xdotool_steps
        )
        return {
            "channel": gui_channel,
            "command": command,
            "delay_s": delay_s,
            "steps": builder(command, esc_first=esc_first),
        }
    return None  # genuinely unreachable: no channel resolved


def build_injection(
    terminal: dict, action: str, *, esc_first: bool = True, delay_s: float = 2.0
) -> dict | None:
    """Build the keystroke-injection PLAN for a GENTLE recovery `action` into a
    resolved `terminal`. PURE. None when the action types no command (esc_nudge /
    hard-restart rungs) OR no channel resolves.

    Channel selection is delegated to `build_command_plan`, so the gentle rungs reach
    exactly the instances the hard rungs do — including ai-maestro agents (CLI channel)
    and Linux GUI terminals, which this function used to declare UNREACHABLE.

    `esc_first` is the hard/soft switch (TRDD-0GPQROC1): the caller passes
    `fleet_recovery.injection_is_hard(diagnosis)` so a LIVE session (cron_dead /
    version_mismatch) gets a SOFT enqueue that preserves its in-flight turn, while a
    FROZEN one keeps the ESC — its wedged turn never ends, so an enqueued command
    would never run.
    """
    command = action_to_command(action)
    if command is None:
        return None  # esc_nudge / hard-restart — not a command-typing injection
    return build_command_plan(terminal, command, esc_first=esc_first, delay_s=delay_s)


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
