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

# --- READ-BACK VERIFICATION (owner directive 2026-08-02) --------------------------------
#
# "wait for the input prompt field to be empty ... after injecting, do not press enter
#  immediately, but reread to verify that only the command is displayed ... otherwise
#  simply try again every 5 seconds, until the field is empty again."
#
# WHY: typing blind into a pane is destructive in two directions. If the user is
# mid-sentence, our text is spliced into THEIR draft — and the Enter we send submits the
# mangled result as if they wrote it. Read-back turns a blind write into a checked one.
#
# ALL THREE CONSTANTS BELOW COME FROM A REAL CAPTURE, not from the docs, and the first one
# is why sampling mattered: the marker is `❯` followed by U+00A0 NO-BREAK SPACE, not an
# ASCII space. `line.startswith("❯ ")` never matches a live Claude Code prompt.
_PROMPT_MARKER = "❯"          # ❯ — starts the input field line
_NBSP = " "                   # what actually follows the marker
_BOX_RULE = "─"               # ─ — the frame above/below the field; ends a wrapped field
_PROMPT_POLL_INTERVAL_S = 5.0      # the owner's "try again after 5 seconds" (a FAILED attempt)
_PROMPT_POLL_TIMEOUT_S = 300.0     # bounded: a hook that never returns is its own outage
# Owner directive, refined 2026-08-02: *"even if the user is reported as present, it should not
# stop the command! it should simply retry every 8 seconds! it must check if in the last 8
# seconds nothing was typed by the user."*
#
# So presence DEFERS, it never CANCELS. The old contract dropped the command on the floor the
# moment someone touched the keyboard — which is how a user who typed the command themselves got
# `USER_PRESENT` and nothing else. Waiting costs a few seconds; discarding costs the request.
_USER_QUIET_S = 8.0                # no keystroke for this long before we attempt


def _inject_giveup_s() -> float:
    """How long the deferral may persist before reporting DEFERRED. Env-overridable so tests
    can force the give-up path without waiting an hour — and so an operator can shorten it on a
    host where a pane is chronically busy. Resolved at CALL time, never frozen at import."""
    raw = os.environ.get("JANITOR_INJECT_GIVEUP_S", "").strip()
    try:
        return max(0.0, float(raw)) if raw else 3600.0
    except ValueError:
        return 3600.0


def extract_prompt_field(pane_text: str) -> str | None:
    """The CURRENT text of the input prompt field, or None when no field is found.

    Returns "" for an empty field — a meaningful value, and deliberately distinct from the
    None that means "could not read". Callers must not conflate them: unknown is never a
    licence to type.

    A long entry WRAPS onto following lines, so the field runs from the marker line to the
    next box rule. Reads the LAST marker in the capture: scrollback can contain earlier
    prompts, and only the live one is the field.
    """
    lines = pane_text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith(_PROMPT_MARKER):
            start = i
    if start is None:
        return None
    head = lines[start].lstrip()[len(_PROMPT_MARKER):]
    parts = [head]
    for line in lines[start + 1:]:
        if _BOX_RULE in line:
            break
        parts.append(line)
    field = "".join(parts)
    # Strip ONLY the NBSP separator and trailing terminal padding. A LEADING ORDINARY SPACE
    # is deliberately preserved: the marker's separator is U+00A0, so an ASCII space after it
    # is something the USER (or a botched paste) put there. `.strip()`ing it made " /compact"
    # read as "/compact" and pass the shape check — the exact spacing the owner ruled out,
    # and the form Claude Code treats as prose rather than a command.
    return field.replace(_NBSP, "").rstrip()


def prompt_field_is_empty(pane_text: str) -> bool:
    """True ONLY when the field was read AND is empty. `None` (unreadable) is False, so an
    unreadable pane is never mistaken for a free one."""
    return extract_prompt_field(pane_text) == ""


def prompt_field_shows_only(pane_text: str, command: str) -> bool:
    """True iff the field contains EXACTLY `command` and nothing else.

    The owner's shape requirement, enforced literally: `/any-command`, with no space before
    or after the `/`. Anything else — leftover user text, a doubled paste, a stray leading
    space that would make Claude Code treat the line as prose rather than a command — fails,
    and the caller retries instead of pressing Enter on it.
    """
    field = extract_prompt_field(pane_text)
    if field is None or field != command.strip():
        return False
    # No space anywhere, and none immediately after the `/` — the owner's literal shape.
    return bool(re.fullmatch(r"/[^\s/][^\s]*", field))


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


def build_clear_field_steps(terminal: Mapping[str, str]) -> list[list[str]] | None:
    """Steps that empty the input field WITHOUT submitting it, or None if unsupported.

    `C-u` (kill-line) is used rather than ESC: in Claude Code ESC interrupts the turn, which is
    a side effect we must not cause while merely tidying up after a bad injection. `C-a C-k` is
    sent as well so a cursor left mid-line still clears to the end.
    """
    kind = terminal.get("kind", "")
    if kind == "tmux" and valid_tmux_pane(terminal.get("pane", "")):
        pane = terminal["pane"]
        return [
            ["RUN", "tmux", "send-keys", "-t", pane, "C-a"],
            ["RUN", "tmux", "send-keys", "-t", pane, "C-k"],
            ["RUN", "tmux", "send-keys", "-t", pane, "C-u"],
        ]
    if kind == "iterm" and re.fullmatch(r"[0-9a-fA-F-]{8,64}", terminal.get("session_id", "")):
        # The SAME C-a / C-k / C-u trio as tmux, as raw control characters (0x01, 0x0b, 0x15).
        # This branch was MISSING until 2026-08-02 and its absence was silent in the worst way:
        # `clear_fn` resolved to None on iTerm, so rule 3's "clear the field and re-inject"
        # did nothing at all, and `inject_until_sent` would loop forever re-reading its own
        # un-cleared text — the deadlock the clear exists to prevent, on the ONLY channel this
        # project actually runs on. Verified live against a real pane, not from documentation.
        return [["RUN", "osascript", "-e", _iterm_session_script(terminal["session_id"], [
            "            write text (character id 1) without newline",
            "            write text (character id 11) without newline",
            "            write text (character id 21) without newline",
        ])]]
    return None


# How many CONSECUTIVE failed pane reads on a READABLE channel to tolerate before giving up.
# Small on purpose: a genuinely wedged pane should be reported, not polled forever — but one
# osascript timeout must not kill a procedure that is otherwise fine.
_MAX_TRANSIENT_UNREADABLE = 3


def _iterm_session_script(sid: str, inner: list[str]) -> str:
    """AppleScript that runs `inner` against ONLY the iTerm session whose id == `sid`.

    Iterates windows → tabs → sessions and matches `(id of s)`. This shape is copied from
    the PROVEN `clear_trigger._build_osascript` / `fleet_inject.iterm_osascript`, and the
    reason is a live failure: the first version of these builders used
    `first window whose id is "<uuid>"`, which iTerm rejects with

        Can't make "ECEF0378-…" into type integer. (-1700)

    because a WINDOW id is an integer while the session id is a UUID. The unit tests asserted
    the argv STRUCTURE and passed happily; only running it against a real pane surfaced it —
    and `_run_steps` swallows stderr (DEVNULL, check=False), so the injector looped forever
    typing nothing, with an empty field on every read-back. One builder, one proven shape.
    """
    lines = [
        'tell application "iTerm2"',
        "  repeat with w in windows",
        "    repeat with t in tabs of w",
        "      repeat with s in sessions of t",
        f'        if (id of s) is "{sid}" then',
        "          tell s",
    ]
    lines += inner
    lines += [
        "          end tell",
        "        end if",
        "      end repeat",
        "    end repeat",
        "  end repeat",
        "end tell",
    ]
    return "\n".join(lines) + "\n"


def channel_is_readable(terminal: Mapping[str, str]) -> bool:
    """True iff this channel CAN be read back at all — i.e. a None from `read_pane_text` means
    "the read failed", not "reading is impossible here".

    Mirrors `read_pane_text`'s own dispatch, including its id validation: a tmux pane or iTerm
    session id that fails validation is not readable, so a tampered id degrades to the
    write-only path rather than being retried three times against an argv we refused to build.
    """
    kind = terminal.get("kind", "")
    if kind == "tmux":
        return valid_tmux_pane(terminal.get("pane", ""))
    if kind == "iterm":
        return bool(re.fullmatch(r"[0-9a-fA-F-]{8,64}", terminal.get("session_id", "")))
    return False


def build_type_only_steps(
    terminal: Mapping[str, str], command: str
) -> list[list[str]] | None:
    """Steps that TYPE `command` into the field but do NOT submit it, or None if unsupported.

    Rule 3 needs typing and Enter to be two separate acts, because the verify happens
    BETWEEN them: type, re-read the pane, and only then press Enter. The existing
    `build_tmux_steps` fuses the two (`send-keys -l <cmd>` immediately followed by
    `send-keys Enter`), which is correct for a blind send and unusable for a verified one —
    by the time we could look, the command has already run.

    A newline in `command` is refused, not escaped: it would submit on its own and defeat
    the split. `applescript_quote` enforces the same invariant on the iTerm side.
    """
    if "\n" in command or "\r" in command:
        raise ValueError("command must be a single line (a newline would submit it early)")
    kind = terminal.get("kind", "")
    if kind == "tmux" and valid_tmux_pane(terminal.get("pane", "")):
        # `-l` is LITERAL: without it tmux interprets the text as key names, so a command
        # containing e.g. "Enter" would be sent as the Enter KEY rather than typed.
        return [["RUN", "tmux", "send-keys", "-t", terminal["pane"], "-l", command]]
    if kind == "iterm" and re.fullmatch(r"[0-9a-fA-F-]{8,64}", terminal.get("session_id", "")):
        return [["RUN", "osascript", "-e", _iterm_session_script(
            terminal["session_id"],
            [f'            write text "{applescript_quote(command)}" without newline'],
        )]]
    return None


def build_submit_steps(terminal: Mapping[str, str]) -> list[list[str]] | None:
    """Steps that press Enter ALONE, or None if unsupported. The other half of the split
    above — sent only after the field has been read back and verified."""
    kind = terminal.get("kind", "")
    if kind == "tmux" and valid_tmux_pane(terminal.get("pane", "")):
        return [["RUN", "tmux", "send-keys", "-t", terminal["pane"], "Enter"]]
    if kind == "iterm" and re.fullmatch(r"[0-9a-fA-F-]{8,64}", terminal.get("session_id", "")):
        # `write text ""` sends the trailing newline ONLY — iTerm appends one unless
        # `without newline` is given, so an empty write IS the Enter keypress. Uses the same
        # verb as the typing half rather than a `character id 13` variant, so both halves
        # succeed or fail together instead of one silently doing nothing.
        return [["RUN", "osascript", "-e", _iterm_session_script(
            terminal["session_id"], ['            write text ""'],
        )]]
    return None


def read_pane_text(terminal: Mapping[str, str]) -> str | None:
    """Read a pane's visible text, or None when this channel cannot be read back.

    Only tmux and iTerm can. `wtype`/`xdotool` are WRITE-ONLY key injectors with no way to
    ask what is on screen, so on those channels the verification below is unavailable — the
    caller must be told (None), never silently told "fine".
    """
    kind = terminal.get("kind", "")
    try:
        if kind == "tmux" and valid_tmux_pane(terminal.get("pane", "")):
            proc = state.run_subprocess(
                ["tmux", "capture-pane", "-p", "-t", terminal["pane"]],
                timeout=10, capture=True, detector_name="terminal_trigger",
            )
            return proc.stdout if proc and proc.returncode == 0 else None
        # Bare-UUID guard, mirroring fleet_inject.valid_session_id — the id is interpolated
        # into an AppleScript string literal, so anything else could break out of it.
        if kind == "iterm" and re.fullmatch(r"[0-9a-fA-F-]{8,64}", terminal.get("session_id", "")):
            script = (
                'tell application "iTerm2" to repeat with w in windows\n'
                '  repeat with t in tabs of w\n    repeat with s in sessions of t\n'
                f'      if id of s is "{terminal["session_id"]}" then return contents of s\n'
                '    end repeat\n  end repeat\nend repeat'
            )
            proc = state.run_subprocess(
                ["osascript", "-e", script], timeout=15, capture=True,
                detector_name="terminal_trigger",
            )
            return proc.stdout if proc and proc.returncode == 0 else None
    except Exception:  # noqa: BLE001 — unreadable is a real answer, not a crash
        return None
    return None


def wait_for_empty_prompt(
    terminal: Mapping[str, str],
    *,
    interval_s: float = _PROMPT_POLL_INTERVAL_S,
    timeout_s: float = _PROMPT_POLL_TIMEOUT_S,
    reader=read_pane_text,
    sleeper=time.sleep,
    clock=time.monotonic,
) -> tuple[bool, str]:
    """Block until the input field is EMPTY. Returns (ok, why).

    `ok=False` means DO NOT TYPE. The unreadable case returns False on purpose: on a
    write-only channel we cannot know whether the user is mid-sentence, and splicing our
    command into their draft — then submitting it with Enter — is exactly the harm this
    exists to prevent. Callers that must still fire on such channels have to opt in
    explicitly, so the risk is visible at the call site rather than buried here.
    """
    deadline = clock() + timeout_s
    while True:
        text = reader(terminal)
        if text is None:
            return False, "pane not readable on this channel"
        if prompt_field_is_empty(text):
            return True, "prompt field empty"
        if clock() >= deadline:
            return False, f"prompt field still busy after {timeout_s:.0f}s"
        sleeper(interval_s)


def verify_then_submit(
    terminal: Mapping[str, str],
    command: str,
    *,
    submit,
    attempts: int = 3,
    interval_s: float = _PROMPT_POLL_INTERVAL_S,
    reader=read_pane_text,
    sleeper=time.sleep,
) -> tuple[bool, str]:
    """After typing `command`, RE-READ and press Enter only if the field shows exactly it.

    `submit` is the callable that actually sends Enter; it is injected so the decision is
    testable without a terminal. Returns (submitted, why).

    Not pressing Enter is the safe outcome: the text sits in the field where the user can
    see and fix it. Pressing Enter on a field we could not verify is the unsafe one — it
    commits whatever is there, under the user's name.
    """
    for i in range(attempts):
        text = reader(terminal)
        if text is not None and prompt_field_shows_only(text, command):
            submit()
            return True, "verified; submitted"
        if i + 1 < attempts:
            sleeper(interval_s)
    field = extract_prompt_field(reader(terminal) or "")
    return False, f"field did not settle to {command!r} (saw {field!r}) — NOT submitting"


def wait_until_pane_free(
    terminal: Mapping[str, str],
    *,
    quiet_s: float = _USER_QUIET_S,
    giveup_s: float | None = None,
    reader=read_pane_text,
    is_typing=None,
    sleeper=time.sleep,
    clock=time.monotonic,
) -> tuple[bool, str]:
    """RULES 1 + 2 only, for callers whose actual typing happens LATER in a detached child.

    Blocks until BOTH hold: the user has typed nothing for `quiet_s`, AND the input field is
    empty. Returns (free, why) — `free=False` means do not proceed.

    This exists because `clear_trigger` fires a DELAYED, detached keystroke phase: the typing
    does not happen here, so `inject_until_sent`'s read-back (rule 3) cannot apply. What CAN
    be checked here is whether a human is using the pane right now — and while the agent is
    mid-turn the field is empty unless the user is TYPING AHEAD, which is precisely the case
    rules 1 and 2 exist to catch.

    Unreadable channels return True ("cannot tell"), NOT False. That is the opposite of
    `wait_for_empty_prompt`, and deliberate: there, refusing merely skips an optimisation;
    here, refusing would resurrect the presence-cancel the owner removed — a command the user
    typed would be silently dropped on any pane we cannot read. Deferring to the caller's own
    timeout is the lesser failure.
    """
    def _default_probe(_t: Mapping[str, str]) -> bool:
        try:
            import user_intent  # noqa: PLC0415

            return user_intent.user_is_present(idle_s=int(quiet_s), env=os.environ)
        except Exception:  # noqa: BLE001
            return False

    probe = _default_probe if is_typing is None else is_typing
    giveup_s = _inject_giveup_s() if giveup_s is None else giveup_s
    deadline = clock() + giveup_s
    while True:
        if probe(terminal):
            if clock() >= deadline:
                return False, f"user still typing after {giveup_s:.0f}s"
            sleeper(quiet_s)
            continue
        text = reader(terminal)
        if text is None:
            return True, "pane not readable — proceeding rather than dropping the command"
        if prompt_field_is_empty(text):
            return True, "pane free"
        if clock() >= deadline:
            return False, f"field still busy after {giveup_s:.0f}s"
        sleeper(quiet_s)


def inject_until_sent(
    terminal: Mapping[str, str],
    command: str,
    *,
    type_fn,
    submit_fn,
    clear_fn=None,
    pre_submit=None,
    quiet_s: float = _USER_QUIET_S,
    retry_s: float = _PROMPT_POLL_INTERVAL_S,
    giveup_s: float | None = None,
    reader=read_pane_text,
    is_typing=None,
    sleeper=time.sleep,
    clock=time.monotonic,
) -> tuple[bool, str]:
    """Keep trying until the command is actually SENT. Returns (sent, why).

    THE THREE RULES (owner, 2026-08-02 — these REPLACE the old presence-cancel entirely):

      1. Inject ONLY when the input field is EMPTY; otherwise re-check after `quiet_s` (8 s).
      2. The moment the user types ANY key, STOP the procedure — **no cleanup, just stop** —
         and retry after `quiet_s` (8 s).
      3. After injection, if the command is MALFORMED **and no key was typed**, clear the field
         and inject again, retrying until it verifies. Only then press Enter.

    Rule 2 is why the old "user is present -> cancel" behaviour is gone, not merely softened:
    presence now DEFERS. Cancelling is what produced a user typing
    `/janitor-handoff-and-clear` at their own keyboard and being told `USER_PRESENT`.

    "No cleanup" in rule 2 is load-bearing and is NOT a simplification for its own sake: if the
    user has started typing, the field contains THEIR keystrokes, so the clear from rule 3
    would delete what they just wrote. Stopping without touching anything is the only safe
    response to "a human is using this pane".

    "Until sent" is bounded by `giveup_s`, deliberately. This runs inside hooks and a daemon
    beat, where a call that never returns is not persistence — it is an outage that also
    silences the heartbeat. Giving up is LOUD (returned + logged), never a silent success.

    `type_fn` / `submit_fn` / `clear_fn` are injected so the decision logic is testable without
    a terminal, and so the caller keeps ownership of which channel actually types.
    """
    def _default_is_typing(_t: Mapping[str, str]) -> bool:
        try:
            import user_intent  # noqa: PLC0415 — lazy; only the inject path needs it

            return user_intent.user_is_present(idle_s=int(quiet_s), env=os.environ)
        except Exception:  # noqa: BLE001
            return False  # unknown presence must not block a requested command forever

    typing_probe = _default_is_typing if is_typing is None else is_typing

    giveup_s = _inject_giveup_s() if giveup_s is None else giveup_s
    deadline = clock() + giveup_s
    last = "not attempted"
    unreadable = 0  # CONSECUTIVE failed reads on a readable channel; reset by any good read
    while True:
        if clock() >= deadline:
            state.log_line("terminal_trigger", f"inject gave up after {giveup_s:.0f}s: {last}")
            return False, f"gave up after {giveup_s:.0f}s ({last})"

        if typing_probe(terminal):
            last = f"user typed within {quiet_s:.0f}s — deferring"
            sleeper(quiet_s)
            continue

        text = reader(terminal)
        if text is None:
            # TWO different Nones, and conflating them was a real defect (TRDD-0BVF4K7E):
            #   * a WRITE-ONLY channel (wtype/xdotool) can NEVER be read — retrying cannot
            #     make it readable, so report instead of looping forever pretending to verify;
            #   * a READABLE channel (tmux/iTerm) that returned None once is a TRANSIENT
            #     failure — an osascript timeout, a `tmux capture-pane` losing a race with a
            #     redraw. Aborting the whole procedure on one blip is why a detached run could
            #     die on its first hiccup while the pane was perfectly fine.
            if not channel_is_readable(terminal):
                return False, "pane not readable on this channel — cannot verify"
            unreadable += 1
            if unreadable > _MAX_TRANSIENT_UNREADABLE:
                return False, f"pane unreadable {unreadable}x in a row — giving up"
            last = f"pane read failed ({unreadable}x) — retrying"
            sleeper(retry_s)
            continue
        unreadable = 0
        # RULE 1 — inject only into an EMPTY field; otherwise re-check after the 8 s window.
        # Uses `quiet_s`, not `retry_s`: a non-empty field means a human is composing, and the
        # owner's rule for "wait for the human" is 8 s. `retry_s` is for OUR failed attempt.
        if not prompt_field_is_empty(text):
            last = f"field not empty ({extract_prompt_field(text)!r})"
            sleeper(quiet_s)
            continue

        type_fn()
        after = reader(terminal)
        if after is not None and prompt_field_shows_only(after, command):
            # `pre_submit` runs HERE and nowhere else: the field is verified and Enter is the
            # very next act, so any state it records cannot outlive a command that never ran.
            # `clear_trigger` writes its resume flags from here — writing them earlier (as it
            # used to, before firing) meant a give-up during the 8s waits left
            # `resume-after-clear.flag` on disk for a /clear that never happened, and the next
            # heartbeat consumed it: issue #105, re-introduced by the very deferral that makes
            # the injector safe. Raising here aborts BEFORE Enter — refusing to submit is the
            # safe direction, so the exception is deliberately not caught.
            if pre_submit is not None:
                pre_submit()
            submit_fn()
            return True, "verified; submitted"

        # MALFORMED — and CLEARING IT IS NOT OPTIONAL. Our own bad text is now sitting in the
        # field, so the next pass's empty-check would see it, wait, see it again... forever.
        # Without this the loop DEADLOCKS on its own garbage: it can recover from the user
        # being busy but never from its own failed injection. (Owner's worked example,
        # 2026-08-02: *"if it is malformed, it will clear the input field and retry the check
        # and will type the command again"*.)
        last = f"field did not settle to {command!r} (saw {extract_prompt_field(after or '')!r})"

        # DID THE USER TYPE BETWEEN OUR INJECTION AND THIS READ-BACK? If so the field is
        # malformed BECAUSE IT NOW CONTAINS THEIR KEYSTROKES, and clearing it would delete
        # what they just wrote — turning a cosmetic retry into data loss. Back off the full
        # QUIET window instead and start over; their text is theirs to finish or discard.
        # (Owner, 2026-08-02: *"if the user typed anything between the injection and the
        # verification, even if the input field is malformed, it should stop and retry after
        # 8 seconds"*.) Checked BEFORE `clear_fn` precisely because the clear is the
        # destructive step.
        if typing_probe(terminal):
            last += " — user typed during injection; backing off without clearing"
            sleeper(quiet_s)
            continue

        if clear_fn is None:
            return False, last + " — and no clear_fn to undo it; refusing to loop on our own text"
        clear_fn()
        sleeper(retry_s)


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


def _encode_payload(
    delay_s: float, steps: list[list[str]], abort_unless_any: list[str] | None = None
) -> str:
    payload: dict = {"delay": float(delay_s), "steps": steps}
    if abort_unless_any:
        # TYPE-TIME guard (TRDD-DXM75JB2): the CHILD re-checks these paths AFTER its
        # sleep, immediately before the first keystroke, and aborts when none exists.
        # Opt-in per payload — callers without the key keep today's behavior exactly.
        payload["abort_unless_any"] = [str(p) for p in abort_unless_any]
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


# --- the CHAINED injector child (TRDD-0BVF4K7E) ----------------------------
#
# `clear_trigger` cannot verify its own keystrokes: it types into the session that is
# RUNNING it, so by the time the keys land the parent turn is over and nothing is left
# in-process to read the pane back. Its old shape was two INDEPENDENT delayed children —
# `/clear` at t=2s, the bootstrap at t=10s — each typing blind. A user who started typing
# at t=1s had their draft spliced and SUBMITTED: exactly the harm the owner's three
# injector rules exist to prevent, in the one command a human is most likely to type by
# hand.
#
# The fix is NOT "apply rule 3 to each phase". That is worse than doing nothing: once
# phase A can DEFER (rule 2), phase B's wall-clock timer decouples from it, so B's
# `/janitor-resume` lands in the UN-cleared session, the dispatcher consumes
# `resume-after-clear.flag`, and the eventually-landing `/clear` strands a session that is
# unarmed AND unresumable. Phase B must chain on A's VERIFIED SUBMIT, never on a clock.
#
# Hence ONE child running ONE sequence, with a real gate between the phases:
# `clear-observed.ts` is stamped by the SessionStart hook on `source == "clear"` — the only
# unambiguous observation that /clear actually happened. Polling it beats parsing the pane,
# which can only ever guess.


def run_chained_inject(
    terminal: Mapping[str, str],
    *,
    first: str,
    then: Sequence[str],
    gate_stamp: Path,
    gate_baseline: int,
    pre_submit_first=None,
    gate_timeout_s: float = 180.0,
    giveup_s: float | None = None,
    sleeper=time.sleep,
) -> tuple[bool, str]:
    """Type `first`, wait for the session it creates to actually EXIST, then type each of
    `then`. Every command is read back and verified before its Enter. Returns (ok, why).

    THIS IS THE WHOLE POINT OF THE REDESIGN. `clear_trigger` used to fire two INDEPENDENT
    delayed children — `/clear` at t=2s, the bootstrap at t=10s — each typing blind. Applying
    rule 3 to each of those separately would be WORSE than leaving it alone: the moment phase A
    can defer (rule 2 — the user touched the keyboard), phase B's wall-clock timer decouples
    from it, so the bootstrap's `/janitor-resume` lands in the UN-CLEARED session, the
    dispatcher consumes `resume-after-clear.flag`, and the `/clear` that finally arrives leaves
    a session that is unarmed AND unresumable. Chaining on the VERIFIED SUBMIT — never on a
    clock — is what makes deferral safe.

    The gate is `clear-observed.ts`, stamped by the SessionStart hook on `source == "clear"`:
    the only unambiguous evidence that /clear happened. `gate_baseline` is read BEFORE typing,
    and the wait requires STRICTLY newer, so an earlier clear's stamp cannot satisfy it.
    Parsing the pane for a "fresh-looking" prompt would only ever be a guess.
    """
    steps_type = build_type_only_steps(terminal, first)
    steps_submit = build_submit_steps(terminal)
    if steps_type is None or steps_submit is None:
        return False, f"channel {terminal.get('kind', '?')!r} cannot type-then-verify"

    def _runner(cmd: str):
        def _do() -> None:
            plan = build_type_only_steps(terminal, cmd)
            if plan:
                _run_steps(plan)
        return _do

    def _submit() -> None:
        plan = build_submit_steps(terminal)
        if plan:
            _run_steps(plan)

    def _clear() -> None:
        plan = build_clear_field_steps(terminal)
        if plan:
            _run_steps(plan)

    ok, why = inject_until_sent(
        terminal, first,
        type_fn=_runner(first), submit_fn=_submit, clear_fn=_clear,
        pre_submit=pre_submit_first, giveup_s=giveup_s, sleeper=sleeper,
    )
    if not ok:
        return False, f"{first} not sent: {why}"

    if not _await_fresh_session(gate_stamp, gate_baseline, timeout_s=gate_timeout_s, sleeper=sleeper):
        # The fresh session never appeared. STOP — do not type the bootstrap into whatever is
        # there now. This is the exact stranding the chain exists to prevent, and reporting a
        # session that needs a manual `/janitor-arm` beats silently arming the wrong one.
        return False, f"{first} submitted but no fresh session within {gate_timeout_s:.0f}s"

    for cmd in then:
        ok, why = inject_until_sent(
            terminal, cmd,
            type_fn=_runner(cmd), submit_fn=_submit, clear_fn=_clear,
            giveup_s=giveup_s, sleeper=sleeper,
        )
        if not ok:
            return False, f"{cmd} not sent: {why}"
    return True, "chain complete"


def _await_fresh_session(
    stamp: Path, baseline: int, *, timeout_s: float, sleeper=time.sleep, clock=time.monotonic
) -> bool:
    """Block until `stamp` reads STRICTLY NEWER than `baseline` — i.e. a /clear actually
    landed and the fresh session's SessionStart hook stamped it. Returns False on timeout.

    `baseline` is captured BEFORE /clear is typed, so a stamp left by an earlier clear can
    never be mistaken for this one. Compared as an integer, not by mtime: an atomic_write
    replaces the file, and a same-second replace would leave mtime indistinguishable.
    """
    deadline = clock() + timeout_s
    while clock() < deadline:
        try:
            if int(stamp.read_text(encoding="utf-8").strip() or 0) > baseline:
                return True
        except (OSError, ValueError):
            pass  # absent or mid-write — that IS the "not yet" answer
        sleeper(1.0)
    return False


def _run_send_payload(payload_b64: str) -> int:
    """CHILD role: decode the pre-resolved plan, wait out the initial delay, then
    run each step. Never raises — a failed send (e.g. the pane closed) degrades to
    the human noticing nothing happened, which is safe."""
    try:
        data = json.loads(base64.b64decode(payload_b64.encode("ascii")).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return 2
    time.sleep(max(0.0, float(data.get("delay", 0.0))))
    guards = data.get("abort_unless_any")
    if isinstance(guards, list) and guards:
        # TYPE-TIME re-check (TRDD-DXM75JB2): the fire-time check in the PARENT ran
        # before this child's sleep; a heartbeat fire can consume the pending flag
        # DURING that sleep, and keystrokes typed after that are queue spam into a
        # session that already resumed. None of the guard files left ⇒ abort silently
        # (the parent already reported FIRED — a no-op here is the desired outcome).
        if not any(Path(str(g)).is_file() for g in guards):
            return 0
    _run_steps(data.get("steps", []))
    return 0


def _run_steps(steps) -> None:
    """Execute RUN/SLEEP-tagged argv steps. Extracted from `_run_send_payload` so the CHAINED
    injector runs keystrokes through the exact same executor as the blind one — two copies of
    this loop would drift, and the copy that drifts is the one that types into a user's pane.

    NEVER RAISES. `check=False` only suppresses a non-zero EXIT; `timeout=` still raises
    `subprocess.TimeoutExpired`, and OSError is raised when the binary is missing. Both used to
    escape this function into a DETACHED child whose stdio is DEVNULL — so a hung `osascript`
    (the macOS TCC automation prompt blocking iTerm control, the exact condition
    `fleet_scan.iterm_automation_blocked` exists to detect) killed the child mid-chain with a
    traceback nobody could ever see, skipping `clear_trigger._run_chain_payload`'s outcome log
    and breaking both children's documented "never raises, always logs" contract. A silent
    give-up is indistinguishable from success, which is the failure shape this module exists to
    prevent — so a failed step is LOGGED and the sequence STOPS. Stopping (rather than typing
    the remaining steps into a pane whose earlier keystrokes never landed) is the safe
    direction: the caller's read-back verification is the authority on whether the send worked,
    and it now sees an unchanged field instead of a dead child."""
    for step in steps:
        if not step:
            continue
        tag, rest = step[0], step[1:]
        if tag == "SLEEP" and rest:
            time.sleep(max(0.0, float(rest[0])))
        elif tag == "RUN" and rest:
            try:
                subprocess.run(  # noqa: S603 - fixed argv, no shell; values are validated/literal
                    rest,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=10,
                )
            except subprocess.TimeoutExpired:
                state.log_line(
                    "terminal_trigger",
                    f"send step timed out after 10s ({rest[0]}) — aborting the remaining steps",
                )
                return
            except OSError as exc:
                state.log_line(
                    "terminal_trigger",
                    f"send step could not run ({rest[0]}): {exc} — aborting the remaining steps",
                )
                return


def _fire_detached_steps(
    delay_s: float, steps: list[list[str]], abort_unless_any: list[str] | None = None
) -> None:
    """Launch a fully-detached child that sleeps then runs the steps, so the ESC it
    sends can't kill the parent and the parent returns immediately. `abort_unless_any`
    (optional) makes the child re-check those files after its sleep and abort when none
    remains — the type-time guard of TRDD-DXM75JB2."""
    subprocess.Popen(  # noqa: S603 - fixed argv (this script + a base64 blob), no shell
        [sys.executable, str(Path(__file__).resolve()), "--__send", _encode_payload(delay_s, steps, abort_unless_any)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def fire_detached_argv(
    delay_s: float, argv: list[str], *, abort_unless_any: list[str] | None = None
) -> None:
    """PUBLIC: run one fixed argv through the SAME detached delayed child as the
    keystroke senders — sleep, optional type-time guard, then the command. Exists so a
    sibling script (resume_trigger's iTerm-osascript path) shares this executor instead
    of embedding its delay inside AppleScript, where no guard can run (TRDD-DXM75JB2)."""
    _fire_detached_steps(delay_s, [["RUN", *argv]], abort_unless_any)


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


def _try_ai_maestro_send(
    commands: Sequence[str], *, dry_run: bool, env: Mapping[str, str], delay_s: float = 0.0
) -> str | None:
    """Best-effort ai-maestro send via the shipped CLI (issue #42). Returns a status
    string on success, or None to fall through to the local terminal send.

    Repointed off the direct `/api/...` calls to `aimaestro-agent.sh` (the frozen
    CLI interface). CLI absent / server down / no cwd match → None → caller degrades
    to the tmux keystroke send. NOTE: the frozen CLI has no raw-ESC primitive, so
    `esc_first` is not honored on this channel — typing a command into a mid-turn
    agent ENQUEUES it (effectively soft) regardless of the requested mode; the local
    tmux/iTerm paths are the ones that honor a hard ESC interrupt.

    AM8JD9SG F9 — the DELIVERY is DETACHED, matching every other channel: only the
    RESOLUTION (one `list --json`, 5 s cap) runs synchronously; the per-command
    `session command` POSTs (~6 s each — a multi-command soft-handoff used to cost
    11-17 s inline, blowing the 5 s hooks.json budget of the calling hook) run in the
    same detached child the tmux channel uses. Consequences, both deliberate:
      * "FIRED:aimaestro" now means "resolved + delivery fired", not "delivery
        confirmed" — identical semantics to "FIRED:tmux" (send-keys never confirmed
        either); a failed POST in the child degrades to "the human notices nothing
        happened", recoverable at the next fire.
      * The F8 partial-delivery ambiguity is GONE structurally: the caller's fallback
        decision now happens strictly BEFORE anything can be typed (resolution
        failure ⇒ None ⇒ tmux fallback re-types safely; after FIRED there is no
        fallback), so a partially-delivered list can never be double-typed.
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
    # 2) Fire each command DETACHED via the CLI (frozen interface over
    #    POST /api/sessions/<tmux>/command). `--newline` presses Enter; requireIdle
    #    stays False (flag omitted); `--` guards a dash-leading command. The child
    #    inherits this process's env, so AID_AUTH rides along exactly as it did on
    #    the synchronous path. Each RUN step carries the child's own 10 s cap.
    steps = [["RUN", cli, "session", "command", tmux, "--newline", "--", c] for c in commands]
    _fire_detached_steps(delay_s, steps)
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
    env: Mapping[str, str], abort_unless_any: Sequence[str] | None = None,
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
    _fire_detached_steps(
        delay_s,
        builder(list(commands), esc_first=esc_first),
        list(abort_unless_any) if abort_unless_any else None,
    )
    return f"FIRED:{channel}"


# How often to re-ask the presence gate while deferring, and how long to keep deferring before
# admitting defeat. The janitor's primary guarantee is that an agent never STOPS, so a late send
# always beats a refused one — and `user_is_present` only looks back 10 s, so a user who pauses
# to read for one poll interval already clears it.
#
# 120 s matches the bound `clear_trigger.main()` arrived at independently (2026-08-02 review):
# the library's own injector default is 3600 s, sized for a DETACHED child, but these calls block
# a FOREGROUND turn, and the presence probe's first rung is machine-wide HID idle — so typing in
# any other app can hold the gate shut while the session merely looks hung. Two minutes is long
# enough to outlast a real pause and short enough that a give-up is still an answer.
_PRESENCE_POLL_S = 3.0
_PRESENCE_WAIT_DEFAULT_S = 120.0


def _presence_wait_budget_s(env: Mapping[str, str]) -> float:
    """Seconds to keep deferring to a busy pane before returning USER_PRESENT.

    0 restores the old abort-on-first-refusal behaviour, for a caller that genuinely cannot
    block. Anything unparseable falls back to the default rather than raising: a malformed knob
    must not be able to turn deferral back into the stranding bug it fixed.
    """
    raw = env.get("CLAUDE_PLUGIN_OPTION_PRESENCE_WAIT_S", "").strip()
    if not raw:
        return _PRESENCE_WAIT_DEFAULT_S
    try:
        value = float(raw)
    except ValueError:
        return _PRESENCE_WAIT_DEFAULT_S
    return value if value >= 0 else _PRESENCE_WAIT_DEFAULT_S


def send_self_command(
    commands: str | Sequence[str], *, delay_s: float = 2.0, esc_first: bool = True,
    dry_run: bool = False, env: Mapping[str, str] | None = None,
    respect_user_presence: bool = True,
    presence_wait_s: float | None = None,
    sleeper=time.sleep,
    abort_unless_any: Sequence[str] | None = None,
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
    never checked, and that asymmetry was the bug. So: **send only when the user is away
    from this pane, or when they explicitly asked** (a fresh `user_intent` token, stamped
    from their raw keystrokes by the UserPromptSubmit hook — which an agent cannot forge).

    It **WAITS for that moment; it does not give up on it.** A busy pane defers the send by
    `presence_wait_s` (default `_PRESENCE_WAIT_DEFAULT_S`, or the
    `CLAUDE_PLUGIN_OPTION_PRESENCE_WAIT_S` knob), re-asking the gate every
    `_PRESENCE_POLL_S`; `USER_PRESENT` comes back only once that whole budget elapses with
    the pane never going quiet. The distinction is the entire point: the janitor's primary
    guarantee is CONTINUITY — an agent that stops is a janitor failure — so a send that
    lands late is a success and a send refused outright is not. Returning `USER_PRESENT`
    eagerly (the pre-2026-08-05 behaviour) handed the human a "type these two commands
    yourself" instruction, which is the automation abdicating to the person it exists to
    relieve, and needlessly: the presence window is only 10 s wide.

    The gate lives HERE, at the single chokepoint every self-trigger funnels through, so
    no caller can forget it. `respect_user_presence=False` exists for a caller that has
    already established consent by other means; it is not a convenience. `presence_wait_s=0`
    restores the old fail-fast shape for a caller that truly cannot block.
    """
    cmds: list[str] = [commands] if isinstance(commands, str) else list(commands)
    e: Mapping[str, str] = os.environ if env is None else env
    # Checked BEFORE any channel is chosen: every channel types into the user's pane, so
    # a gate on one channel would be a gate on none. Dry-run is exempt (it sends nothing).
    if respect_user_presence and not dry_run:
        # Forward the resolved env so the PER-PANE presence gate (TRDD, 2026-07-16) reads the same
        # pane id this send targets — otherwise the reader would fall back to os.environ and the
        # gate could disagree with the channel it is gating.
        #
        # DEFER, NEVER ABORT (owner report 2026-08-05). This used to `return USER_PRESENT` on the
        # first refusal, which stranded the whole continuity chain: the human was told to type
        # `/clear` + `/janitor-arm` themselves, i.e. the automation gave the work back to the person
        # it exists to relieve. That is a continuity-rule violation, and it was pure self-injury —
        # `user_is_present` uses a TEN-SECOND window, so the gate that refused would have opened on
        # its own a few seconds later. Waiting is what the pane-level machinery below already does
        # (`inject_until_sent` -> `wait_until_pane_free`); this gate simply never reached it.
        #
        # So: poll the SAME predicate until it clears, then fall through and send. USER_PRESENT is
        # now returned only after `giveup_s` of a genuinely continuously-busy pane — a real answer
        # ("you never stopped typing"), not a refusal to try. `injection_allowed` consumes an intent
        # token ONLY when it returns True, so polling it cannot burn the user's explicit request.
        allowed, _ = user_intent.injection_allowed(cmds, env=e)
        if not allowed:
            budget = _presence_wait_budget_s(e) if presence_wait_s is None else presence_wait_s
            deadline = time.monotonic() + budget
            while not allowed and time.monotonic() < deadline:
                sleeper(_PRESENCE_POLL_S)
                allowed, _ = user_intent.injection_allowed(cmds, env=e)
            if not allowed:
                return USER_PRESENT
    # Inside an ai-maestro agent the server API is the authoritative way to reach
    # the agent's own terminal. Best-effort — any failure (server down, no match,
    # unconfirmed POST) falls through to the local terminal send below; ai-maestro
    # agents run in tmux, so that fallback works too (TRDD-db169d9e R4).
    if state.in_ai_maestro_agent_env(e):
        api = _try_ai_maestro_send(cmds, dry_run=dry_run, env=e, delay_s=delay_s)
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
            cmds, delay_s=delay_s, esc_first=esc_first, dry_run=dry_run, env=e,
            abort_unless_any=abort_unless_any,
        ) or USE_ITERM_PATH
    if kind == "tmux":
        pane = (e.get("TMUX_PANE") or "").strip()
        if not valid_tmux_pane(pane):
            return "NO_AUTO_TERMINAL:tmux"
        if dry_run:
            keys = ("ESC+" if esc_first else "") + "+".join(cmds)
            return f"DRY_RUN:tmux:{pane}:{keys}@{delay_s}s"
        _fire_detached_steps(
            delay_s,
            build_tmux_steps(pane, cmds, esc_first=esc_first),
            list(abort_unless_any) if abort_unless_any else None,
        )
        return "FIRED:tmux"
    return f"NO_AUTO_TERMINAL:{kind}"  # unreachable while _DELEGATE_KINDS == {"tmux"}


def main() -> int:
    # Child entry: `terminal_trigger.py --__send <base64-plan>`.
    # Wrapped so the child's "never raises" contract is enforced at the BOUNDARY, not only by
    # every callee remembering it. This process is detached with DEVNULL stdio, so an escaping
    # exception is a traceback written to nowhere — indistinguishable from a successful send.
    if len(sys.argv) >= 3 and sys.argv[1] == "--__send":
        try:
            return _run_send_payload(sys.argv[2])
        except Exception as exc:  # noqa: BLE001 - a detached child must log, never vanish
            state.log_line("terminal_trigger", f"send child aborted: {exc!r}")
            return 1

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
