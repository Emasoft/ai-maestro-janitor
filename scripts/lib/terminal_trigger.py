#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Terminal-aware self-trigger send-abstraction (TRDD-db169d9e R3).

The janitor's self-trigger commands (`/compact`, `/reload-plugins`) need to type a
slash-command into THIS session's OWN pane, and the mechanism differs per terminal.
The terminal is identified by `state.terminal_kind()` — a PROCESS-ANCESTRY walk, not
fragile `$TERM_PROGRAM` inference.

Division of labour with the two entry scripts (`compact_trigger.py` /
`reload_trigger.py`):

  - This module owns the NON-iTerm backends. Today that is **tmux** (the terminal
    ai-maestro agents run in): a detached, delayed `tmux send-keys` ESC -> command
    -> Enter at the pane named by `$TMUX_PANE`.
  - On **Linux with no tmux**, a best-effort keystroke send into the FOCUSED
    GUI-terminal window via the compositor's input tool — `wtype` (Wayland) or
    `xdotool` (X11) — reaches a session running directly in gnome-terminal /
    konsole / xterm. tmux stays PREFERRED (per-pane, focus-independent) whenever
    present; this is only the fallback for a GUI terminal with no tmux, and it is
    Linux-only so macOS/iTerm dispatch is untouched. (TRDD-ME8V2YJF)
  - For **iTerm** (and any terminal we don't yet automate) `send_self_command`
    returns the sentinel `USE_ITERM_PATH`, and the caller falls back to its own
    proven iTerm osascript path (or prints its degrade marker when even that
    isn't available). This keeps the working iTerm path — and its tests —
    untouched while adding tmux.

kitty / WezTerm / Apple Terminal etc. are future best-effort backends; until they
can be verified on a real host they degrade to `USE_ITERM_PATH` (→ the caller's
"ask the human to run it manually" path), which is exactly today's behaviour for
every non-iTerm terminal — never a regression.

The keystroke delivery runs in a DETACHED, delayed CHILD so the ESC it sends can't
kill the parent mid-turn, and so the parent returns instantly. The target pane is
resolved in the PARENT (which still has the full process ancestry) and passed to
the child as data — a child that got reparented to init couldn't re-resolve it.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import state  # noqa: E402
import user_intent  # noqa: E402

# Returned when the user is AT the terminal and did not ask for this command. Nothing is
# sent: typing into a pane whose human is mid-sentence destroys what they were typing.
# The caller must surface it and let the user run the command themselves.
USER_PRESENT = "USER_PRESENT"

# Terminals this module automates beyond iTerm. tmux is first-class (verifiable +
# the ai-maestro agent host). Add "kitty"/"wezterm" here once a real host confirms
# their send commands; until then they fall through to USE_ITERM_PATH (degrade).
_DELEGATE_KINDS = frozenset({"tmux"})

# A tmux pane id is `%<n>` (e.g. `%3`). $TMUX_PANE is set by tmux for the active
# pane. Validate before interpolating it into an argv — never trust an env var.
_TMUX_PANE_RE = re.compile(r"^%[0-9]+$")


def valid_tmux_pane(pane: str) -> bool:
    """True iff `pane` is a bare tmux pane id (`%<n>`) safe to place on a
    `tmux send-keys -t <pane>` argv. Anything else — notably a leading `-`, which
    tmux would parse as a FLAG rather than a target — is rejected. This is the tmux
    counterpart to the iTerm `valid_session_id` UUID gate, so BOTH injection sinks
    are hardened symmetrically (a tampered TTY→pane map can't reach the argv)."""
    return bool(_TMUX_PANE_RE.match(pane.strip()))

# Sentinel: the caller should use its own iTerm-osascript path (covers iTerm and
# every not-yet-automated terminal, whose fallback is "ask the human").
USE_ITERM_PATH = "USE_ITERM_PATH"

# On this Claude Code build a SINGLE ESC only cancels the in-flight TOOL (e.g. a running
# Bash command), NOT the whole turn — so a HARD self-trigger interrupt must send TWO ESCs:
# the first clears the running tool, the second ends the turn. With one ESC, a command typed
# while the agent is still mid-turn merely ENQUEUES behind the live turn and doesn't run until
# the turn happens to end — the "/compact stuck in the command queue" bug (TRDD-L87BQ2Y9,
# user-observed 2026-07-01). Both ESCs are harmless on an already-idle pane, so the
# double-press is safe whether or not a tool is actually running. This is the ONE source of
# truth for every hard-interrupt builder: the tmux/wtype/xdotool steps below AND the iTerm
# osascript builders in compact_trigger / reload_trigger / reload_skills_trigger / fleet_inject
# (via iterm_esc_lines()).
HARD_INTERRUPT_ESC_COUNT = 2
# Per-ESC settle. A str so it drops cleanly into BOTH a tmux SLEEP step (`["SLEEP", "0.6"]`)
# and an iTerm osascript `delay 0.6`.
_ESC_SETTLE_S = "0.6"


def applescript_quote(command: str) -> str:
    """`command` escaped for interpolation inside an AppleScript double-quoted string —
    the SSOT sink-hardening for every iTerm `write text "…"` builder (audit finding 3).

    Those builders used to raw f-string-interpolate the command, guarded only by the fact
    that every caller happens to pass a fixed internal literal (`/janitor-arm`, `/compact`,
    `/reload-plugins --force`, `claude --continue`). But `fleet_inject.build_command_plan`
    and `fleet_restart.command_injection_plan` ADVERTISE themselves as builders for an
    "arbitrary"/"raw" command, so a future caller passing untrusted text would inject
    AppleScript — and on the iTerm channel ONLY, since tmux/wtype/xdotool pass argv (or `-l`
    literal) and are already safe. Harden the sink, not the callers, so it holds no matter
    who calls it.

    Backslash FIRST, then the quote — the reverse order would re-escape the backslashes the
    quote-escaping just introduced. A newline is REFUSED rather than escaped: it cannot
    appear inside an AppleScript string literal, and it would mean typing a second,
    unreviewed command into the user's shell."""
    if "\n" in command or "\r" in command:
        raise ValueError("command must be a single line (a newline would submit a second command)")
    return command.replace("\\", "\\\\").replace('"', '\\"')


def iterm_esc_lines(indent: str = "            ") -> list[str]:
    """AppleScript lines for a HARD interrupt inside an iTerm ``tell s`` block:
    ``HARD_INTERRUPT_ESC_COUNT`` raw-ESC writes, each followed by a settle delay. Shared by
    every iTerm self-trigger / fleet-recovery osascript builder so the two-ESC rule (see
    ``HARD_INTERRUPT_ESC_COUNT``) has a single source of truth. ``indent`` is the leading
    whitespace matching the builder's ``tell s`` block (default 12 spaces)."""
    out: list[str] = []
    for _ in range(HARD_INTERRUPT_ESC_COUNT):
        out.append(f"{indent}write text (character id 27) without newline")
        out.append(f"{indent}delay {_ESC_SETTLE_S}")
    return out


def build_tmux_steps(
    pane: str, commands: str | Sequence[str], *, esc_first: bool = True
) -> list[list[str]]:
    """The ordered send sequence for a tmux pane: an OPTIONAL leading ESC, then each
    command typed as LITERAL text and submitted with Enter. Pure — returns argv steps
    tagged RUN / SLEEP.

    `commands` is a SINGLE command string OR a list of them. A bare string is normalized
    to a one-element list — CRITICAL, because a str is itself a `Sequence[str]` of
    characters, so iterating it directly would send one keystroke PER CHARACTER. Direct
    callers that pass a single command string (`fleet_inject`, `fleet_restart`) rely on
    this normalization.

    `esc_first=True` (the HARD default) prepends `send-keys … Escape`, which interrupts
    an in-flight turn / clears partial input so the command runs NOW. `esc_first=False`
    (the SOFT path) OMITS the ESC: the command is typed while the agent is mid-turn and
    Claude Code ENQUEUES it — it runs only after the current turn ends, so no in-flight
    work is discarded. Multiple commands are typed back-to-back (all ESC-free after the
    single optional leading ESC), so `["/janitor-write-handoff", "/compact"]` enqueues
    both in order — the input queue then serialises them across turns.
    `-l <command>` sends the command as LITERAL text (so `/compact` isn't parsed as a
    tmux key name); a trailing `Enter` submits each.
    """
    cmds: list[str] = [commands] if isinstance(commands, str) else list(commands)
    steps: list[list[str]] = []
    if esc_first:
        # TWO ESCs (HARD_INTERRUPT_ESC_COUNT): one clears a running tool, one ends the turn.
        for _ in range(HARD_INTERRUPT_ESC_COUNT):
            steps.append(["RUN", "tmux", "send-keys", "-t", pane, "Escape"])
            steps.append(["SLEEP", _ESC_SETTLE_S])
    for i, command in enumerate(cmds):
        if i:
            steps.append(["SLEEP", "0.4"])  # let each enqueued command register before the next
        steps.append(["RUN", "tmux", "send-keys", "-t", pane, "-l", command])
        steps.append(["RUN", "tmux", "send-keys", "-t", pane, "Enter"])
    return steps


def build_wtype_steps(
    commands: str | Sequence[str], *, esc_first: bool = True
) -> list[list[str]]:
    """The Wayland (`wtype`) send sequence, mirroring `build_tmux_steps`: an OPTIONAL
    leading ESC, then each command typed as LITERAL text and submitted with Enter.
    Pure — returns RUN/SLEEP-tagged argv steps.

    Like the tmux builder, a bare string is normalized to a one-element list (a str is
    itself a `Sequence[str]` of characters, so iterating it would send one keystroke
    per character). `wtype -k Escape` / `wtype -k Return` press keys by keysym; a bare
    positional arg is typed VERBATIM (`wtype /compact` types "/compact") — the janitor's
    commands are slash-tokens that never lead with a dash, so no literal guard is needed.
    Unlike tmux there is no per-pane target: `wtype` types into the FOCUSED window.
    (TRDD-ME8V2YJF)
    """
    cmds: list[str] = [commands] if isinstance(commands, str) else list(commands)
    steps: list[list[str]] = []
    if esc_first:
        # TWO ESCs (HARD_INTERRUPT_ESC_COUNT): one clears a running tool, one ends the turn.
        for _ in range(HARD_INTERRUPT_ESC_COUNT):
            steps.append(["RUN", "wtype", "-k", "Escape"])
            steps.append(["SLEEP", _ESC_SETTLE_S])
    for i, command in enumerate(cmds):
        if i:
            steps.append(["SLEEP", "0.4"])
        steps.append(["RUN", "wtype", command])
        steps.append(["RUN", "wtype", "-k", "Return"])
    return steps


def build_xdotool_steps(
    commands: str | Sequence[str], *, esc_first: bool = True
) -> list[list[str]]:
    """The X11 (`xdotool`) send sequence, mirroring `build_tmux_steps`: an OPTIONAL
    leading ESC, then each command typed as LITERAL text and submitted with Enter.
    Pure — returns RUN/SLEEP-tagged argv steps.

    A bare string is normalized to a one-element list (same char-iteration trap as the
    tmux/wtype builders). `xdotool key Escape` / `xdotool key Return` press keys;
    `xdotool type --clearmodifiers -- <text>` types the literal command (`--clearmodifiers`
    releases any held modifier; `--` ends option parsing so even a dash-leading command is
    safe). Like `wtype`, there is no per-pane target — it types into the FOCUSED window.
    (TRDD-ME8V2YJF)
    """
    cmds: list[str] = [commands] if isinstance(commands, str) else list(commands)
    steps: list[list[str]] = []
    if esc_first:
        # TWO ESCs (HARD_INTERRUPT_ESC_COUNT): one clears a running tool, one ends the turn.
        for _ in range(HARD_INTERRUPT_ESC_COUNT):
            steps.append(["RUN", "xdotool", "key", "Escape"])
            steps.append(["SLEEP", _ESC_SETTLE_S])
    for i, command in enumerate(cmds):
        if i:
            steps.append(["SLEEP", "0.4"])
        steps.append(["RUN", "xdotool", "type", "--clearmodifiers", "--", command])
        steps.append(["RUN", "xdotool", "key", "Return"])
    return steps


def _encode_payload(delay_s: float, steps: list[list[str]]) -> str:
    return base64.b64encode(
        json.dumps({"delay": float(delay_s), "steps": steps}).encode("utf-8")
    ).decode("ascii")


def _run_send_payload(payload_b64: str) -> int:
    """CHILD role: decode the pre-resolved plan, wait out the initial delay, then
    run each step. Never raises — a failed send (e.g. the pane closed) degrades to
    the human noticing nothing happened, which is safe."""
    try:
        data = json.loads(base64.b64decode(payload_b64.encode("ascii")).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return 2
    time.sleep(max(0.0, float(data.get("delay", 0.0))))
    for step in data.get("steps", []):
        if not step:
            continue
        tag, rest = step[0], step[1:]
        if tag == "SLEEP" and rest:
            time.sleep(max(0.0, float(rest[0])))
        elif tag == "RUN" and rest:
            subprocess.run(  # noqa: S603 - fixed argv, no shell; values are validated/literal
                rest,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
            )
    return 0


def _fire_detached_steps(delay_s: float, steps: list[list[str]]) -> None:
    """Launch a fully-detached child that sleeps then runs the steps, so the ESC it
    sends can't kill the parent and the parent returns immediately."""
    subprocess.Popen(  # noqa: S603 - fixed argv (this script + a base64 blob), no shell
        [sys.executable, str(Path(__file__).resolve()), "--__send", _encode_payload(delay_s, steps)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


# --- ai-maestro send via the SHIPPED CLI (issue #42; TRDD-db169d9e R4) ------
#
# When running INSIDE an ai-maestro agent, the AUTHORITATIVE way to type a command
# into the agent's own terminal goes through the ai-maestro server — but NOT by
# calling the server's HTTP API directly. Per the ecosystem decoupling rule
# (ai-maestro@8a2cc269: "no plugin element may call the server API directly — hooks
# and MCP included"), the janitor couples to the IMMUTABLE CLI layer the ai-maestro
# installer ships to ~/.local/bin, never the endpoints (the API changes constantly;
# the CLI is a frozen interface that POSTs the same endpoints behind it). So:
# `aimaestro-agent.sh list --json` to find this agent (CWD match) → its tmux session
# → `aimaestro-agent.sh session command <tmux> --newline -- <cmd>`. Every step is
# best-effort: a missing CLI, a down server, or an unconfirmed send returns None so
# the caller falls back to the local tmux keystroke send (ai-maestro agents run in
# tmux, so that path works too). Auth (AID_AUTH / AIMAESTRO_SUDO_TOKEN) is read by
# the CLI from the inherited env — the janitor never handles a token itself.


def _resolve_aimaestro_cli(env: Mapping[str, str]) -> str | None:
    """Resolve the ai-maestro CLI: $AIMAESTRO_CLI → ~/.local/bin → PATH; None if absent.

    The unified installer drops `aimaestro-agent.sh` in ~/.local/bin; an explicit
    `$AIMAESTRO_CLI` overrides (as the COS scripts do) so it resolves under a
    minimal hook/cron env where ~/.local/bin may not be on PATH.
    """
    override = env.get("AIMAESTRO_CLI")
    if override and Path(override).is_file() and os.access(override, os.X_OK):
        return override
    home = env.get("HOME") or os.path.expanduser("~")
    cand = Path(home) / ".local" / "bin" / "aimaestro-agent.sh"
    if cand.is_file() and os.access(cand, os.X_OK):
        return str(cand)
    return shutil.which("aimaestro-agent.sh")


def _run_aimaestro_cli(
    cli: str, args: list[str], *, env: Mapping[str, str], timeout: float
) -> subprocess.CompletedProcess[str] | None:
    """Run `<cli> <args…>` with the inherited env; None on ANY failure (best-effort)."""
    try:
        return subprocess.run(
            [cli, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=dict(env),
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _agent_working_dir(agent: dict) -> str | None:
    wd = agent.get("workingDirectory")
    if not (isinstance(wd, str) and wd):
        sess = agent.get("session")
        wd = sess.get("workingDirectory") if isinstance(sess, dict) else None
    return wd if isinstance(wd, str) and wd else None


def _agent_tmux_session(agent: dict) -> str | None:
    sess = agent.get("session")
    if isinstance(sess, dict):
        ts = sess.get("tmuxSessionName")
        if isinstance(ts, str) and ts:
            return ts
    ts = agent.get("tmuxSessionName")
    return ts if isinstance(ts, str) and ts else None


def match_agent_tmux(agents: list, cwd_candidates: list[str]) -> str | None:
    """Pure: the tmux session of the agent whose workingDirectory equals — or is a
    parent of — any cwd candidate. Returns None when nothing matches."""
    cands = [os.path.realpath(c) for c in cwd_candidates if c]
    # MOST-SPECIFIC match wins (longest workingDirectory), not registry order: with the
    # parent-prefix rule, an agent registered at a broad root (e.g. ~/Code) matches EVERY
    # project under it, and list order would route this session's keystrokes (ESC,
    # /compact, …) into that OTHER agent's pane. Keystroke injection must never guess.
    #
    # AM8JD9SG F5: an EXACT-workdir TIE (two ai-maestro agents registered on the SAME
    # repo — a documented dev+reviewer pattern) is NOT disambiguable by cwd. The old
    # `len(wdr) > best_len` silently kept the FIRST such agent (registry order — the very
    # thing this docstring forbids), routing keystrokes into a coin-flip pane. On a genuine
    # ambiguous tie we now REFUSE (return None) so the caller degrades to "ask the user"
    # rather than typing an ESC + /compact into the wrong agent's in-flight turn.
    best_ts: str | None = None
    best_len = -1
    best_ambiguous = False
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        wd = _agent_working_dir(agent)
        if not wd:
            continue
        wdr = os.path.realpath(wd)
        if any(c == wdr or c.startswith(wdr + os.sep) for c in cands):
            ts = _agent_tmux_session(agent)
            if not ts:
                continue
            if len(wdr) > best_len:
                best_ts, best_len, best_ambiguous = ts, len(wdr), False
            elif len(wdr) == best_len and ts != best_ts:
                # Same specificity, DIFFERENT target session → we cannot choose safely.
                best_ambiguous = True
    return None if best_ambiguous else best_ts


def _try_ai_maestro_send(commands: Sequence[str], *, dry_run: bool, env: Mapping[str, str]) -> str | None:
    """Best-effort ai-maestro send via the shipped CLI (issue #42). Returns a status
    string on success, or None to fall through to the local terminal send.

    Repointed off the direct `/api/...` calls to `aimaestro-agent.sh` (the frozen
    CLI interface). CLI absent / server down / unconfirmed → None → caller degrades
    to the tmux keystroke send. A multi-command list (the soft-handoff case) is typed
    one CLI call per command, in order. NOTE: the frozen CLI has no raw-ESC primitive,
    so `esc_first` is not honored on this channel — typing a command into a mid-turn
    agent ENQUEUES it (effectively soft) regardless of the requested mode; the local
    tmux/iTerm paths are the ones that honor a hard ESC interrupt.
    """
    cli = _resolve_aimaestro_cli(env)
    if not cli:
        return None
    # 1) Enumerate agents → find THIS agent's tmux session by cwd match. `list
    #    --json` returns the same agent objects the API did, so the pure matcher is
    #    reused unchanged.
    proc = _run_aimaestro_cli(cli, ["list", "--json"], env=env, timeout=5.0)
    if proc is None or proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        agents = json.loads(proc.stdout)
    except ValueError:
        return None
    if isinstance(agents, dict) and isinstance(agents.get("agents"), list):
        agents = agents["agents"]
    if not isinstance(agents, list):
        return None
    tmux = match_agent_tmux(agents, [os.getcwd(), env.get("CLAUDE_PROJECT_DIR", "")])
    if not tmux:
        return None
    if dry_run:
        return f"DRY_RUN:aimaestro:{tmux}:{'+'.join(commands)}"
    # 2) Type each command into that agent's terminal via the CLI (frozen interface
    #    over POST /api/sessions/<tmux>/command). `--newline` presses Enter;
    #    requireIdle stays False (flag omitted). `--` guards a dash-leading command.
    for i, command in enumerate(commands):
        sent = _run_aimaestro_cli(
            cli, ["session", "command", tmux, "--newline", "--", command],
            env=env, timeout=6.0,
        )
        if sent is None or sent.returncode != 0:
            if i == 0:
                return None  # nothing delivered yet → safe to fall back and re-type all
            # AM8JD9SG F8: PARTIAL delivery. Commands [0:i] already ran on the agent, so
            # returning None (→ caller's tmux fallback re-types the WHOLE list) would
            # double-run them — e.g. a soft-handoff ['/janitor-write-handoff', '/compact']
            # would run the handoff twice and /compact on the already-compacted session.
            # Report partial so the caller treats it as delivered and does NOT re-send;
            # losing the undelivered tail (cmds[i:]) is recoverable at the next fire and
            # strictly safer than the duplication.
            return f"FIRED:aimaestro:partial:{i}/{len(commands)}"
    return "FIRED:aimaestro"


# --- Linux GUI-terminal channel (wtype on Wayland / xdotool on X11) ---------
#
# A Linux janitor session that is NOT inside tmux runs directly in a GUI terminal
# (gnome-terminal, konsole, xterm, …). Those have no per-pane addressing like tmux's
# $TMUX_PANE, so we type into the FOCUSED window via the compositor's input tool:
# `wtype` under Wayland, `xdotool` under X11. Best-effort by nature — it only lands
# correctly when this session's terminal has focus — which matches the module's
# degrade philosophy (a miss = "the human notices nothing happened"). tmux stays
# PREFERRED (focus-independent) and is chosen first in send_self_command; this is the
# fallback path only. Linux-only by construction so macOS/iTerm never changes.


def _resolve_linux_gui_channel(env: Mapping[str, str]) -> str | None:
    """Pick the Linux GUI-terminal keystroke tool, or None to degrade.

    Wayland (`$WAYLAND_DISPLAY`) → `wtype`; X11 (`$DISPLAY`) → `xdotool` — but only
    when the tool is actually on PATH. Returns None when off Linux (so a macOS host
    with XQuartz's `$DISPLAY` set never diverts off the iTerm path), when the session
    has no graphical display, or when neither tool is installed — the caller then fails
    open to `USE_ITERM_PATH`. Wayland is tried first because `xdotool` via XWayland
    can't inject into native Wayland windows. (TRDD-ME8V2YJF)
    """
    if not sys.platform.startswith("linux"):
        return None
    if env.get("WAYLAND_DISPLAY") and shutil.which("wtype"):
        return "wtype"
    if env.get("DISPLAY") and shutil.which("xdotool"):
        return "xdotool"
    return None


def _try_linux_gui_send(
    commands: Sequence[str], *, delay_s: float, esc_first: bool, dry_run: bool,
    env: Mapping[str, str],
) -> str | None:
    """Best-effort Linux GUI-terminal send via wtype/xdotool into the FOCUSED window.
    Returns a `FIRED:`/`DRY_RUN:` status on success, or None to fall through to
    `USE_ITERM_PATH`. The detached delayed child + step machinery is shared with the
    tmux path, so the ESC-first / soft-enqueue semantics carry over unchanged.
    (TRDD-ME8V2YJF)
    """
    channel = _resolve_linux_gui_channel(env)
    if channel is None:
        return None
    builder = build_wtype_steps if channel == "wtype" else build_xdotool_steps
    if dry_run:
        keys = ("ESC+" if esc_first else "") + "+".join(commands)
        return f"DRY_RUN:{channel}:focused:{keys}@{delay_s}s"
    _fire_detached_steps(delay_s, builder(list(commands), esc_first=esc_first))
    return f"FIRED:{channel}"


def send_self_command(
    commands: str | Sequence[str], *, delay_s: float = 2.0, esc_first: bool = True,
    dry_run: bool = False, env: Mapping[str, str] | None = None,
    respect_user_presence: bool = True,
) -> str:
    """Send one or more fixed slash-commands (e.g. `/compact`) to this session's own
    pane, choosing the mechanism by `state.terminal_kind()`.

    `commands` is a single command string OR a list of them (typed back-to-back — the
    soft-handoff case enqueues `["/janitor-write-handoff", "/compact"]`). `esc_first`
    selects HARD vs SOFT: `True` (default) prepends a raw ESC that interrupts the
    in-flight turn so the command runs NOW; `False` OMITS the ESC so the command is
    merely typed while the agent is mid-turn and Claude Code enqueues it until the turn
    ends (no in-flight work lost). ESC honoring is per-channel: the local tmux/iTerm
    paths obey `esc_first`; the ai-maestro CLI has no raw-ESC primitive, so it always
    enqueues (documented in `_try_ai_maestro_send`).

    Returns a status string:
      - `USE_ITERM_PATH` — kind is iTerm or a terminal we don't automate; the caller
        should use its own iTerm-osascript path (which itself degrades to "ask the
        human" when iTerm isn't actually available).
      - `FIRED:<kind>` — a detached delayed send was launched.
      - `DRY_RUN:<kind>:<keys>@<delay>s` — dry-run plan (nothing fired); `<keys>` shows
        an `ESC+` prefix for a hard send and the `+`-joined command list.
      - `NO_AUTO_TERMINAL:<kind>` — the kind is delegated but its target was
        unresolvable (e.g. `$TMUX_PANE` malformed); caller degrades.
      - `USER_PRESENT` — the user is AT the terminal and did not ask for this. Nothing
        was sent; the caller must tell the user to run the command themselves.

    THE PRESENCE GATE (`respect_user_presence`, default True). Typing into a pane whose
    human is mid-sentence CLOBBERS what they were typing — this is not theoretical: a
    `[janitor-reload]` marker fired `/reload-plugins` into the user's pane while they
    were writing and truncated their message. The *fleet* injector has always refused to
    type into a pane whose user is active (`fleet_stop.is_injectable`); the *self*-trigger
    never checked, and that asymmetry was the bug. So: **inject only when the user is
    away, or when the user explicitly asked** (a fresh `user_intent` token, stamped from
    their raw keystrokes by the UserPromptSubmit hook — which an agent cannot forge).

    The gate lives HERE, at the single chokepoint every self-trigger funnels through, so
    no caller can forget it. `respect_user_presence=False` exists for a caller that has
    already established consent by other means; it is not a convenience.
    """
    cmds: list[str] = [commands] if isinstance(commands, str) else list(commands)
    e: Mapping[str, str] = os.environ if env is None else env
    # Checked BEFORE any channel is chosen: every channel types into the user's pane, so
    # a gate on one channel would be a gate on none. Dry-run is exempt (it sends nothing).
    if respect_user_presence and not dry_run:
        # Forward the resolved env so the PER-PANE presence gate (TRDD, 2026-07-16) reads the same
        # pane id this send targets — otherwise the reader would fall back to os.environ and the
        # gate could disagree with the channel it is gating.
        allowed, _ = user_intent.injection_allowed(cmds, env=e)
        if not allowed:
            return USER_PRESENT
    # Inside an ai-maestro agent the server API is the authoritative way to reach
    # the agent's own terminal. Best-effort — any failure (server down, no match,
    # unconfirmed POST) falls through to the local terminal send below; ai-maestro
    # agents run in tmux, so that fallback works too (TRDD-db169d9e R4).
    if state.in_ai_maestro_agent_env(e):
        api = _try_ai_maestro_send(cmds, dry_run=dry_run, env=e)
        if api is not None:
            return api
    kind = state.terminal_kind()
    if kind not in _DELEGATE_KINDS:
        # tmux is PREFERRED (the delegate kind, handled below). With no tmux, a Linux
        # GUI-terminal session can still be reached by typing into its focused window
        # via wtype/xdotool. Off Linux or with neither tool present this returns None,
        # so macOS/iTerm keeps its unchanged USE_ITERM_PATH degrade. (TRDD-ME8V2YJF)
        # _try_linux_gui_send returns None (degrade) or a truthy FIRED:/DRY_RUN: status.
        return _try_linux_gui_send(
            cmds, delay_s=delay_s, esc_first=esc_first, dry_run=dry_run, env=e
        ) or USE_ITERM_PATH
    if kind == "tmux":
        pane = (e.get("TMUX_PANE") or "").strip()
        if not valid_tmux_pane(pane):
            return "NO_AUTO_TERMINAL:tmux"
        if dry_run:
            keys = ("ESC+" if esc_first else "") + "+".join(cmds)
            return f"DRY_RUN:tmux:{pane}:{keys}@{delay_s}s"
        _fire_detached_steps(delay_s, build_tmux_steps(pane, cmds, esc_first=esc_first))
        return "FIRED:tmux"
    return f"NO_AUTO_TERMINAL:{kind}"  # unreachable while _DELEGATE_KINDS == {"tmux"}


def main() -> int:
    # Child entry: `terminal_trigger.py --__send <base64-plan>`.
    if len(sys.argv) >= 3 and sys.argv[1] == "--__send":
        return _run_send_payload(sys.argv[2])

    import argparse

    ap = argparse.ArgumentParser(description="Type a slash-command into this session's own pane.")
    ap.add_argument("command", help="the slash-command to send, e.g. /compact")
    ap.add_argument("--delay", type=float, default=2.0, help="seconds before sending (lets the turn settle)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument(
        "--soft",
        action="store_true",
        help="deprecated no-op alias — SOFT (enqueue, no ESC) is now the default (TRDD-0GPQROC1)",
    )
    mode.add_argument(
        "--hard",
        action="store_true",
        help="press ESC first — interrupt the in-flight turn so the command runs NOW",
    )
    ap.add_argument("--dry-run", action="store_true", help="print the plan, do not fire")
    args = ap.parse_args()
    # SOFT is the default (TRDD-0GPQROC1): the command enqueues at the turn boundary
    # so no in-flight work is lost; --hard restores the ESC-interrupt.
    print(send_self_command(args.command, delay_s=args.delay, esc_first=args.hard, dry_run=args.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
