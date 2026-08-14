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

  NOT a general-purpose channel — unreachable while the server lives (janitor#218):
  the ``aimaestro_session``/``aimaestro_cli`` identity fields exist ONLY when the
  scan's agent list ANSWERED (``tag_aimaestro_identity`` no-ops otherwise), and that
  same successful list makes ``instance_is_server_owned`` tag the instance
  ``server_owned`` — which every injection consumer treats as hands-off (the
  ``_DIAGNOSIS_RECOVERY`` table maps it to None ahead of dead/frozen; the rate-limit
  wake pass targets only ``healthy``; ``fleet_stop.select_stop_targets`` skips it
  explicitly). And with the server dead the list fails, so the fields are never
  attached at all. The one deliberate opening is the operator adoption override
  (``$JANITOR_AIMAESTRO_SERVER_STATE`` forced down): a human explicitly adopting the
  harness fleet — never an automatic path. Today even that is moot from the daemon:
  the list 401s without ``AID_AUTH`` (AM8JD9SG F6), so the daemon never sees a tag;
  the live consumer of this argv shape is the SESSION-side self-trigger
  (``terminal_trigger.send_self_command``), a harness agent driving its OWN pane.
- **Linux GUI** (wtype/xdotool) → reuses ``terminal_trigger.build_wtype_steps`` /
  ``build_xdotool_steps`` (the same builders self-trigger uses), typing into the
  FOCUSED window — best-effort, last resort, tagged by ``fleet_scan`` only when
  no tmux/iTerm channel resolved.

Everything here is PURE / dry-run-able: build the payload, inspect it, THEN fire.
This module covers the gentle rungs: the command-TYPING rungs (rearm/reload/update)
AND ``esc_nudge`` — an ESC-ONLY injection that types NO command (``build_esc_plan``,
the flood-safe recovery for a rate-limited session, TRDD-P7WU40G9). The hard-restart
rungs (relaunch/force_restart/resurrect) kill/spawn processes and live in the daemon
task behind the crash-loop guard, not here.
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

# How long `fire()` waits for the ai-maestro CLI to confirm ONE `session command`
# (TRDD-3VW434Q8). Deliberately the SAME bound the self-trigger path already proved for
# the identical CLI verb (terminal_trigger._try_ai_maestro_send, timeout=6.0) — one verb,
# one bound, so the two callers can never disagree about how long "delivered" may take.
AIMAESTRO_CLI_TIMEOUT_S = 6.0

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
    # The daemon-owned rate-limit RESUME wake (TRDD-X07E7HTN, D1 v1). Fired ONLY
    # into a NON-frozen, rate-limited pane (a `frozen` pane gets esc_nudge, never a
    # typed command — TRDD-P7WU40G9), soft-enqueue (esc_first=False): the enqueued
    # `/janitor-resume` runs the dispatcher stub, which is the single-consumer of
    # rate-limited.flag, so this is the free daemon analogue of resume_trigger.py's
    # self-send. NEVER the bare `[janitor-resume]` MARKER — a typed marker is untrusted
    # content (dispatch._defang_foreign_markers neutralizes it); a typed marker would be
    # inert, so the slash command is the only working channel, and routing through it
    # makes reachability self-verifying (the command turn completes only when the API is
    # reachable).
    "resume": "/janitor-resume",
}


def action_to_command(action: str) -> str | None:
    """The slash-command a command-typing recovery `action` injects, or None when
    the action types no command (esc_nudge = ESC only; hard-restart rungs = daemon)."""
    return _ACTION_COMMAND.get(action)


# ESC-ONLY recovery actions — an injection that sends ESC and types NO command
# (TRDD-P7WU40G9). `esc_nudge` is the recovery for a `frozen` (rate-limited) session:
# ESC breaks Claude Code's retry-watchdog wait, and the session's own rate-limited.flag
# → [janitor-resume] resumes the work. Typing a command there would BUFFER on the
# retry-blocked input line and flood, so these actions carry no command at all.
_ESC_ONLY_ACTIONS = frozenset({"esc_nudge"})


def is_esc_only(action: str) -> bool:
    """True iff `action` is an ESC-only recovery (sends ESC, types no command)."""
    return action in _ESC_ONLY_ACTIONS


def iterm_esc_only_osascript(session_id: str, *, delay_s: float = 2.0) -> str:
    """AppleScript that targets ONLY the iTerm session whose id == `session_id` and sends
    ESC (`HARD_INTERRUPT_ESC_COUNT` presses) with NO `write text` — the flood-safe recovery
    for a rate-limited session. The caller MUST have validated `session_id` (`valid_session_id`).
    Shares the ESC SSOT `terminal_trigger.iterm_esc_lines`, so the two-ESC rule matches the
    command-typing path exactly; there is no command string to escape here."""
    esc = "\n".join(terminal_trigger.iterm_esc_lines()) + "\n"
    return (
        f"delay {delay_s}\n"
        'tell application "iTerm2"\n'
        "  repeat with w in windows\n"
        "    repeat with t in tabs of w\n"
        "      repeat with s in sessions of t\n"
        f'        if (id of s) is "{session_id}" then\n'
        "          tell s\n"
        f"{esc}"
        "          end tell\n"
        "        end if\n"
        "      end repeat\n"
        "    end repeat\n"
        "  end repeat\n"
        "end tell\n"
    )


def build_esc_plan(terminal: dict, *, delay_s: float = 2.0) -> dict | None:
    """Build an ESC-ONLY injection plan (send ESC, type NO command) for a resolved `terminal`,
    or None when no ESC-capable channel resolves. PURE. Mirrors `build_command_plan`'s channel
    selection MINUS the ai-maestro CLI channel — that channel has no raw-ESC primitive (typing
    into a managed agent only ENQUEUES), and an ai-maestro agent is `server_owned` and never
    recovered by this daemon anyway. The plan shape matches the command plans (same `channel`
    keys + `osascript` / `steps`+`delay_s`), so `fire()` handles it unchanged.

    Every keystroke step is JUST the two ESCs: the tmux/wtype/xdotool builders return ESC-only
    steps when passed an EMPTY command list with `esc_first=True`, and the iTerm branch uses the
    dedicated `iterm_esc_only_osascript`.
    """
    pane = terminal.get("tmux_pane", "").strip()
    if pane and terminal_trigger.valid_tmux_pane(pane):
        return {
            "channel": "tmux",
            "command": "",
            "delay_s": delay_s,
            "steps": terminal_trigger.build_tmux_steps(pane, [], esc_first=True),
        }
    sid = terminal.get("iterm_session_id", "").strip().split(":")[-1].strip()
    if sid and valid_session_id(sid):
        return {
            "channel": "iterm",
            "command": "",
            "delay_s": delay_s,
            "osascript": iterm_esc_only_osascript(sid, delay_s=delay_s),
        }
    gui_channel = terminal.get("linux_gui_channel", "").strip()
    if gui_channel in ("wtype", "xdotool"):
        builder = (
            terminal_trigger.build_wtype_steps
            if gui_channel == "wtype"
            else terminal_trigger.build_xdotool_steps
        )
        return {
            "channel": gui_channel,
            "command": "",
            "delay_s": delay_s,
            "steps": builder([], esc_first=True),
        }
    return None  # no ESC-capable channel resolved


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

    Fallback order — aimaestro (SOFT sends to a server-managed pane, AM8JD9SG F10) ->
    tmux -> iterm -> aimaestro (hard-intent fall-through) -> linux-gui. Plan shapes::

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
    session = terminal.get("aimaestro_session", "").strip()
    cli = terminal.get("aimaestro_cli", "").strip()
    if session and cli and not esc_first:
        # AM8JD9SG F10 — a SERVER-MANAGED pane prefers the server's own channel over raw
        # tmux send-keys typed behind the server's back: the CLI send goes through the
        # server's queueing/session model, so the server SEES the command it is asked to
        # deliver instead of finding foreign keystrokes in a pane it owns. SOFT only:
        # this channel has no ESC primitive (typing into a mid-turn agent ENQUEUES
        # regardless), so a HARD intent falls through to tmux/iterm below — the ESC is
        # the point of a hard send and only the keystroke channels can deliver one.
        return {
            "channel": "aimaestro",
            "command": command,
            "argv": aimaestro_command_argv(cli, session, command),
        }
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
    if session and cli:
        # HARD-intent fall-through for an aimaestro-only identity (no tmux pane, no
        # iTerm id): an enqueue that ignores the requested ESC is still better than
        # UNREACHABLE — the reachability parity this builder exists for (see WHY above).
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
    FROZEN one keeps the ESC — its retry-blocked turn never ends, so an enqueued command
    would never run.

    An ESC-ONLY action (`esc_nudge`, the `frozen`/rate-limited recovery — TRDD-P7WU40G9)
    is routed to `build_esc_plan`: it sends ESC and types NO command, so nothing can
    accumulate on the retry-blocked input line. `esc_first` is irrelevant there (the plan
    IS the ESC).
    """
    if is_esc_only(action):
        return build_esc_plan(terminal, delay_s=delay_s)
    command = action_to_command(action)
    if command is None:
        return None  # hard-restart rung — not a command-typing injection (daemon handles it)
    return build_command_plan(terminal, command, esc_first=esc_first, delay_s=delay_s)


def _readback_identity(terminal: dict, plan: dict) -> dict[str, str] | None:
    """Map a fired plan's CHANNEL to the `terminal_trigger`-shaped identity dict its
    read-back primitives expect (`{"kind": "tmux", "pane": ...}` /
    `{"kind": "iterm", "session_id": ...}`), or None for a channel with no read-back at
    all (aimaestro CLI, Linux GUI wtype/xdotool — write-only, per `read_pane_text`'s own
    docstring). `fleet_inject`'s own `terminal` dict uses different keys
    (`tmux_pane`/`iterm_session_id`) than `terminal_trigger`'s self-trigger shape
    (`pane`/`session_id`) — this is the one place that translates between them."""
    channel = plan.get("channel")
    if channel == "tmux":
        return {"kind": "tmux", "pane": terminal.get("tmux_pane", "").strip()}
    if channel == "iterm":
        sid = terminal.get("iterm_session_id", "").strip().split(":")[-1].strip()
        return {"kind": "iterm", "session_id": sid}
    return None


def command_plan_field_busy(terminal: dict, plan: dict) -> bool:
    """True iff `plan` TYPES A COMMAND (never an ESC-only plan) and the target pane's own
    input field is CONFIRMED non-empty right now — i.e. firing would type on top of
    whatever is already showing there, most dangerously a permission prompt.

    WHY THIS EXISTS (2026-07-17 incident, `session_liveness.awaiting_user` docstring): the
    fleet guardian typed `/janitor-arm` straight into an open approval dialog. The
    `awaiting_user` transcript check only catches a pending tool_use that is VISIBLE in the
    transcript (ExitPlanMode / AskUserQuestion) — a Claude Code PERMISSION prompt is pure UI
    state and appears in NO transcript line, so a session sitting on one is diagnosed exactly
    like a genuinely dead/frozen one and reaches the command-typing path uncovered. Reading
    the field back is the only signal that actually observes UI state, so it is the backstop
    the transcript check cannot be.

    ESC-only plans (`build_esc_plan`, `plan["command"] == ""`) are NEVER gated here — ESC
    cannot approve or select anything, only dismiss, so it stays the safe unconditional
    unblock the frozen/rate-limited recovery relies on.

    Deliberately PERMISSIVE (returns False, i.e. "not busy, go ahead") whenever busy-ness
    cannot be PROVEN: an unreadable channel (`channel_is_readable` False — aimaestro CLI,
    wtype/xdotool) or a read that fails (`read_pane_text` returns None — a transient tmux/
    osascript timeout). This is a REFUSAL gate, not a proof-of-safety gate: it only ever
    blocks a fire it can affirmatively show is unsafe, so an unreadable channel is never
    silently and permanently locked out of recovery — trading the covered incident for a
    worse, blanket one would defeat the point of the fix.
    """
    if not plan.get("command"):
        return False  # ESC-only — never gated
    rt = _readback_identity(terminal, plan)
    if rt is None or not terminal_trigger.channel_is_readable(rt):
        return False  # cannot prove busy on this channel — allow (today's behavior)
    text = terminal_trigger.read_pane_text(rt)
    if text is None:
        return False  # read failed — cannot prove busy — allow
    return not terminal_trigger.prompt_field_is_empty(text)


# Every slash-command the janitor itself ever TYPES into a pane. A field showing exactly one of
# these is our own unsubmitted send, not a foreign dialog — see `field_holds_our_command`.
# Sourced from `_ACTION_COMMAND` (the recovery vocabulary) plus the fleet-stop and
# model-fallback commands, so adding a recovery action cannot silently fall out of the set.
def _our_command_vocabulary() -> frozenset[str]:
    extra = {"/janitor-disarm", "/janitor-pause", "/clear", "/compact", "/reload-skills"}
    return frozenset(v for v in _ACTION_COMMAND.values() if v) | extra


def field_holds_our_command(pane_text: str | None) -> str:
    """The janitor command a pane's input field is holding UNSUBMITTED, or "" if none.

    THE THIRD CAUSE (janitor#261). `command_plan_field_busy` above asks one question — is the
    field non-empty — and the daemon logs the answer as "a permission prompt or other text may
    be showing". That enumeration names two causes and omits the one the janitor CREATES: a
    command it typed itself, SOFT (no ESC, deliberately, so no in-flight turn is cut short),
    that has not run yet.

    It is self-perpetuating, which is what makes it compounding rather than transient: the field
    is non-empty BECAUSE we typed into it, so the guardian declines, so nothing drains it, so it
    stays non-empty — and the session that most needs rescuing is the one least able to receive
    it. The blast radius grew on 2026-08-13, when janitor#257 moved the last four self-triggers
    off the `USER_PRESENT` cancel: a pane that previously got nothing typed into it now gets the
    command.

    Matching against a CLOSED VOCABULARY rather than a sender-recorded ledger is deliberate
    (advisor, 2026-08-14). A "what we last typed here" record would have to be written by every
    typing path — `fleet_inject.fire`, both `terminal_trigger` send paths, `fleet_restart` — and
    ONE missed writer silently reintroduces the exact bug, on top of staleness and pane-reuse
    questions. The field content is already the record; it needs no second source of truth.

    EXACT match only, after strip. A field holding our command plus anything else is a human
    editing it, and must keep counting as busy.
    """
    text = (pane_text or "").strip()
    if not text:
        return ""
    field = terminal_trigger.extract_prompt_field(pane_text or "")
    candidate = (field or text).strip()
    return candidate if candidate in _our_command_vocabulary() else ""


def field_holds_our_queued_command(terminal: dict, plan: dict) -> str:
    """The janitor command sitting UNSUBMITTED in this pane's field, or "" — the I/O wrapper
    over `field_holds_our_command`.

    Kept here rather than at the daemon call site so the pane READ and the vocabulary MATCH stay
    on the same side of the module boundary: `daemon.py` does not import `terminal_trigger` at
    all, and reaching for it there would add a dependency purely to re-implement this.
    """
    rt = _readback_identity(terminal, plan)
    if rt is None or not terminal_trigger.channel_is_readable(rt):
        return ""
    return field_holds_our_command(terminal_trigger.read_pane_text(rt))


def build_submit_plan(terminal: dict, plan: dict) -> dict | None:
    """A plan that presses Enter ALONE into `terminal` — used to FINISH a send of ours that is
    sitting unsubmitted, instead of declining forever because it is sitting there.

    Enter is the minimal correct actuation here: the command is already in the field and is
    already ours, so submitting types no new text and cannot concatenate onto a half-typed
    line. Re-typing the command would risk exactly that.

    `plan` is the injection we were ABOUT to fire; it is used only to resolve the same channel
    the read-back used, so the Enter lands in the pane we actually read.
    """
    rt = _readback_identity(terminal, plan)
    if rt is None:
        return None
    steps = terminal_trigger.build_submit_steps(rt)
    if not steps:
        return None
    return {"channel": rt.get("kind", ""), "steps": steps, "delay_s": 0.0, "command": ""}


def fire(plan: dict | None) -> bool:
    """Fire a built injection plan. Returns True iff the injection is believed DELIVERED,
    False otherwise. Safe to call with None (a declined plan) → False.

    The four KEYSTROKE channels (iterm / tmux / wtype / xdotool) are spawned fully
    DETACHED — so the daemon never blocks and is never killed by the very ESC the plan
    sends — and for them "spawned" is the only outcome available: a local keystroke
    sender has no exit code that means "the pane rejected it".

    The `aimaestro` channel is different in kind and is run SYNCHRONOUSLY (see its branch):
    it is an RPC to a server, so it HAS a meaningful exit code, and it sends no ESC to the
    daemon's own pane — the detachment rationale above simply does not apply to it.

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
            # SYNCHRONOUS + bounded, unlike the detached keystroke channels above
            # (TRDD-3VW434Q8). This branch used to fire-and-forget with stdout/stderr
            # → DEVNULL and no returncode check, so it returned True on SPAWN, never on
            # DELIVERY — and every consumer believed it: _fire_fleet_stop stamped an
            # UNDELIVERED machine-wide stop as delivered (so it was never retried while
            # the flag was held, and that session's cron kept billing turns straight
            # through a stop the user believed was in effect), and the F3 recovery audit
            # recorded "fired" for a command that never landed. That is not hypothetical:
            # a down server, an unauthenticated CLI, or a stale tmux session name all
            # produce it today — and a 403 will, once ai-maestro strict-classifies the
            # inject verb (their issue #54).
            #
            # It is safe to wait here, and it was never necessary not to: the "must never
            # block" rule this branch inherited from the iTerm/tmux plans defends against
            # the ESC those plans send KILLING THE DAEMON THAT LAUNCHED THEM. This channel
            # is an RPC to a server; it sends no ESC to the daemon's pane, so it faces no
            # such threat. The bound is the one the self-trigger path
            # (terminal_trigger._try_ai_maestro_send) has already proven for the identical
            # CLI verb. A timeout is a failure, not a success: it means undelivered.
            proc = subprocess.run(  # noqa: S603 - fixed argv (resolved CLI + validated session), no shell
                plan["argv"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=AIMAESTRO_CLI_TIMEOUT_S,
                check=False,
            )
            return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
    return False
