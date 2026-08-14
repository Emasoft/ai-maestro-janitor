#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Backing script for /janitor-reload-plugins (analogue of compact_trigger.py).

Fires a DETACHED, delayed /reload-plugins at THIS session's own iTerm pane
so the agent can pick up freshly auto-updated plugin hooks/skills WITHOUT the
human typing the command. The heartbeat's `[janitor-reload]` marker asks the
agent to "silently run /reload-plugins", but the Skill tool refuses built-in
slash commands — so, exactly like the compact trigger, the only working path is
to type the command into this session's own pane via osascript.

SOFT is the default (TRDD-0GPQROC1): the command is typed without ESC, so it
ENQUEUES and runs after the current turn ends — a reload is never worth killing
the in-flight turn. `--hard` presses ESC first when the reload must happen NOW.

UNLIKE the compact trigger there is NO resume directive: /reload-plugins reloads
plugin code in place and does NOT discard the conversation, so nothing needs to
be recorded for an auto-resume — the turn simply continues after the reload.

The delay + detach are load-bearing: the script must NOT be killed by the ESC it
may send, so it returns immediately and the keystrokes fire ~delay seconds
later (after the agent ends its turn). It targets ONLY the session whose UUID
matches $ITERM_SESSION_ID — never other panes — so concurrent Claude instances
are untouched.

Outside iTerm ($ITERM_SESSION_ID unset) self-trigger isn't available: the script
prints NO_ITERM and the skill asks the user to run /reload-plugins manually.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS / "lib"))
sys.path.insert(0, str(_SCRIPTS))  # sibling triggers (clear_trigger) live here, not in lib/
import clear_trigger  # noqa: E402  -- the verified /clear chain we reuse for --shrink
import state  # noqa: E402  -- the reload-ack rollback (janitor#257)
import terminal_trigger  # noqa: E402
import token_meter as tm  # noqa: E402  -- RELOAD_GUARD_DEFAULT_THRESHOLD, shared with dispatch

RELOAD_CMD = "/reload-plugins --force"

# Seconds between the post-clear `/reload-plugins` and the `/janitor-arm` that follows it.
# `/reload-plugins` fires NO hook (measured — token_meter.py, `claude-code-hook-types`
# memory), so its completion is UNOBSERVABLE and nothing can gate on it. If `/janitor-arm`
# is dispatched into a mid-swap plugin registry it can be rejected as an unknown command
# while the chain still reports OK — and since `/clear` destroyed the session-scoped cron,
# that leaves a session both cleared AND unwakeable. This pause shrinks the window; it does
# not close it, which is why the arm state is re-checked afterwards rather than assumed.
RELOAD_SETTLE_S = 4.0

# `auto` is the default: shrink ONLY above the same context threshold at which dispatch
# already refuses to emit `[janitor-reload]`. Below it a reload is cheap and a `/clear`
# would destroy the conversation to save nothing — at 320k, clearing to reach the ~305k
# floor is negative value on the owner's own metric.
SHRINK_MODES = ("auto", "never", "force")


def shrink_threshold(env: dict[str, str] | None = None) -> int:
    """The context-token threshold above which a reload shrinks first.

    Reads the SAME env var and default as dispatch's reload guard, deliberately: the guard
    and this decision must agree, or dispatch defers a reload that this script would have
    handled cheaply (or vice versa) and the two disagree silently.
    """
    src = os.environ if env is None else env
    return state.coerce_int(
        src.get("CLAUDE_PLUGIN_OPTION_RELOAD_CONTEXT_GUARD_THRESHOLD"),
        tm.RELOAD_GUARD_DEFAULT_THRESHOLD,
        detector_name="reload-trigger",
        var_name="CLAUDE_PLUGIN_OPTION_RELOAD_CONTEXT_GUARD_THRESHOLD",
    )


def should_shrink(mode: str, *, context_tokens: int | None, threshold: int, hard: bool) -> bool:
    """PURE. True iff this reload should `/clear` first. Tested without a terminal.

    Three refusals, each deliberate and each failing toward the RECOVERABLE outcome — a
    reload that costs tokens is recoverable, a `/clear` that destroys an un-handed-off
    conversation is not:
      - `--hard` NEVER shrinks. Hard means urgent (a security fix, a marker whose new code
        must land now); a shrink adds a clear + re-arm + resume before the reload happens.
      - an UNREADABLE context (`None`) never shrinks in `auto`. We refuse to clear on a
        guess; the cost of being wrong is one expensive turn, versus a destroyed session.
      - below the threshold never shrinks: the reload is already cheap there.
    `force` overrides the threshold (but still not `--hard`) so the path stays testable and
    a human can demand it.
    """
    if hard or mode == "never":
        return False
    if mode == "force":
        return True
    return context_tokens is not None and context_tokens >= threshold


def _context_tokens() -> int | None:
    """Live context size, or None when it cannot be read (never raises).

    None is a REFUSAL to shrink in `auto` mode, not a zero — see `should_shrink`.
    """
    try:
        import cold_cache_compact  # noqa: PLC0415 -- lazy: fail-open when the lib is absent

        return cold_cache_compact.context_tokens_for(
            cold_cache_compact.newest_transcript(state.project_root())
        )
    except Exception as exc:  # noqa: BLE001 -- an unreadable context must never break the reload
        state.log_line("reload-trigger", f"context read failed, not shrinking: {exc}")
        return None

# An iTerm session id is a hex UUID (8-4-4-4-12). $ITERM_SESSION_ID is
# `<tty>:<UUID>`. We interpolate the UUID into an `osascript -e` string, so we
# MUST reject anything that isn't hex+dashes — an env var is attacker-settable,
# and a value like `x:" then do shell script "rm -rf ~" --` would otherwise
# inject AppleScript. A security plugin must not ship its own injection sink.
_UUID_RE = re.compile(r"^[0-9A-Fa-f-]{8,64}$")


def _build_osascript(uuid: str, delay_s: float, *, esc_first: bool = True) -> str:
    """AppleScript that targets ONLY the session whose id == uuid, then (optionally) a
    raw ESC followed by /reload-plugins.

    `esc_first=True` (default) writes a raw ESC byte first
    (`write text (character id 27)`), clearing any half-typed input / interrupting an
    in-flight turn so the reload runs NOW — the HARD path. `esc_first=False` (SOFT)
    sends NO ESC, so `/reload-plugins` is typed while the agent is mid-turn and Claude
    Code enqueues it until the turn ends (the reload then applies without cutting the
    turn short). `write text "/reload-plugins"` types and submits the command (iTerm's
    write text appends a return)."""
    lines = [
        f"delay {delay_s}",
        'tell application "iTerm2"',
        "  repeat with w in windows",
        "    repeat with t in tabs of w",
        "      repeat with s in sessions of t",
        f'        if (id of s) is "{uuid}" then',
        "          tell s",
    ]
    if esc_first:
        # TWO ESCs (terminal_trigger.HARD_INTERRUPT_ESC_COUNT): one clears a running tool,
        # one ends the turn — else /reload-plugins enqueues behind the still-alive turn.
        lines += terminal_trigger.iterm_esc_lines()
    # --force: without it a plugin whose code is mid-use can refuse the reload and
    # stay on the old cached version (user directive 2026-07-10) — every janitor
    # sender of /reload-plugins forces for this reason.
    lines.append('            write text "/reload-plugins --force"')
    lines += [
        "          end tell",
        "        end if",
        "      end repeat",
        "    end repeat",
        "  end repeat",
        "end tell",
    ]
    return "\n".join(lines) + "\n"


def _fire(script: str) -> None:
    """Launch osascript fully detached so the parent returns before its own ESC."""
    subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        ["osascript", "-e", script],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _undeliverable(why: str) -> None:
    """The reload could NOT be typed — print the legacy marker AND un-consume the signal.

    janitor#257 found this rollback attached to the presence cancel, which was the wrong
    outcome to attach it to (that cancel is now gone entirely — presence defers at the pane,
    it never refuses). The defect it fixes is real and OUTLIVES the cancel: `[janitor-reload]`
    is once-per-reload-generation and `dispatch` advances its ack at EMISSION time, before
    delivery can possibly be known. So any non-delivery silently consumes the only signal that
    a reload was needed — the session keeps running stale plugin code with nothing left to say
    so, and "asked the human, who never did it" is indistinguishable from "reloaded".

    Rolling the ack back makes the next fire re-emit. `dispatch`'s own reload-guard already
    uses this discipline for the high-context case ("ack left unadvanced; re-checked on the
    next fire"); this applies it to the outcomes only knowable AFTER the marker is out, which
    is why they must be UNDONE rather than withheld. Rollback semantics (why 0, why an absent
    stamp stays absent) live in `state.rollback_marker_ack` — shared with the skills trigger,
    which has the same emission-time ack and the same delivery failure modes.
    """
    state.rollback_marker_ack("reload-acked.ts", actor="reload-trigger", why=why)
    print("NO_ITERM")


def main() -> int:
    ap = argparse.ArgumentParser(description="Self-trigger /reload-plugins at this session's pane.")
    ap.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="seconds to wait before sending ESC -> /reload-plugins (lets the turn settle)",
    )
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument(
        "--soft",
        action="store_true",
        help="deprecated no-op alias — SOFT (enqueue, no ESC) is now the default "
        "(TRDD-0GPQROC1, user directive 2026-07-10)",
    )
    mode.add_argument(
        "--hard",
        action="store_true",
        help="press ESC first — interrupt the in-flight turn so the reload runs NOW; "
        "a reload is rarely that urgent, so this is opt-in",
    )
    ap.add_argument(
        "--shrink",
        choices=SHRINK_MODES,
        default="auto",
        help="shrink context (/clear + bootstrap) BEFORE reloading, so the cache-prefix "
        "break lands on a near-floor context instead of a 500k one. auto (default) = only "
        "above the reload-guard threshold; force = always; never = never. --hard implies never.",
    )
    ap.add_argument(
        "--directive",
        default="",
        help="one-line resume pointer recorded for the post-clear auto-resume (shrink path "
        "only; defaults to a pointer at the link-only agent-handoff.md)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan, but do NOT fire osascript (for tests)",
    )
    args = ap.parse_args()
    # SOFT is the default (TRDD-0GPQROC1): typed while the agent is mid-turn, the
    # command ENQUEUES and runs at the turn boundary — no in-flight work is lost.
    # A reload never justifies killing the caller's own turn; --hard restores ESC.
    esc_first = args.hard

    # SHRINK-THEN-RELOAD (owner directive 2026-08-14). `/reload-plugins` breaks the
    # prompt-cache prefix, so the next turn re-caches the WHOLE conversation at ~1.25x
    # instead of reading it at ~0.1x — measured, and already documented at
    # token_meter.RELOAD_GUARD_DEFAULT_THRESHOLD. Clearing FIRST makes that break land on a
    # near-floor context. The reload is the FIRST bootstrap step, ahead of /janitor-arm,
    # because between `/clear` and the first API turn there is no cache written yet: the
    # reload there is not merely cheaper, it is FREE. Running it after arm would re-bill the
    # freshly-written base at 1.25x on the very next turn.
    #
    # This also terminates a real deadlock. dispatch's reload guard defers `[janitor-reload]`
    # above the same threshold on the assumption that "the context shrinks on its own" — which
    # is false for an unattended session, so the reload deferred FOREVER and the session ran
    # stale plugin code silently. Shrinking is what makes that deferral end.
    ctx = _context_tokens() if args.shrink == "auto" else None
    threshold = shrink_threshold()
    if should_shrink(args.shrink, context_tokens=ctx, threshold=threshold, hard=args.hard):
        then = [RELOAD_CMD, *clear_trigger.BOOTSTRAP_CMDS]
        if args.dry_run:
            print(f"DRY_RUN would chain /clear then {' -> '.join(then)} (context={ctx})")
            return 0
        directive = args.directive.strip() or (
            "read .janitor/state/agent-handoff.md FIRST (link-only handoff — follow its "
            "wikimem/TRDD links via memgrep recall on demand), then resume your prior "
            "in-flight task. Plugins were reloaded during this clear."
        )
        spawned, why = clear_trigger.spawn_shrink_chain(
            then=then,
            directive=directive,
            delay=args.delay,
            settle_between_s=RELOAD_SETTLE_S,
        )
        if spawned:
            state.log_line(
                "reload-trigger",
                f"shrink-then-reload chain spawned (context={ctx}, threshold={threshold})",
            )
            print("RELOAD_SHRINK_CHAIN_SPAWNED")
            return 0
        # The pane cannot be read back, so the chain cannot verify its own `/clear`. Fall
        # through to a DIRECT reload rather than clearing blind: an expensive reload is
        # recoverable, an unverifiable `/clear` is not.
        state.log_line("reload-trigger", f"shrink unavailable ({why}) — reloading directly")

    # Prefer a non-iTerm automatable terminal (tmux) when detected via process
    # ancestry. iTerm / unknown / not-yet-automated terminals return USE_ITERM_PATH
    # and fall through to the proven iTerm-osascript path below (TRDD-db169d9e R3).
    # NO PRESENCE CANCEL (owner directive 2026-08-02, migrated here 2026-08-13 — janitor#257).
    # This used to gate on `user_intent.injection_allowed` and, on refusal, `print("USER_PRESENT")`
    # and return. That is the retired one-shot model: it handed the work back to the human it
    # exists to relieve, and the owner's replacement has exactly one input — the last keystroke.
    # Presence now DEFERS at the pane level inside `terminal_trigger.inject_until_sent`: wait for
    # an empty field, stop the instant a key is pressed, push 8 s ahead per keystroke, and NEVER
    # stop trying. So the send is never refused for presence and `USER_PRESENT` cannot come back.
    sent = terminal_trigger.send_self_command(
        "/reload-plugins --force",
        delay_s=args.delay,
        esc_first=esc_first,
        dry_run=args.dry_run,
        respect_user_presence=False,
    )
    if sent != terminal_trigger.USE_ITERM_PATH:
        if sent.startswith("FIRED:"):
            print("RELOAD_FIRED")
        elif sent.startswith("DRY_RUN:"):
            print(f"DRY_RUN {sent.split(':', 1)[1]}")
        else:  # NO_AUTO_TERMINAL:<kind> — can't auto-send; ask the human (legacy marker)
            _undeliverable(f"no automatable terminal ({sent})")
        return 0

    iterm = os.environ.get("ITERM_SESSION_ID", "").strip()
    if not iterm:
        _undeliverable("iTerm path chosen but $ITERM_SESSION_ID is unset")
        return 0
    uuid = iterm.split(":")[-1].strip()
    if not _UUID_RE.match(uuid):
        # Malformed / untrusted session id — refuse to build the osascript rather
        # than risk AppleScript injection. The skill asks the user to reload manually.
        print(f"BAD_ITERM_ID {uuid[:32]}", file=sys.stderr)
        _undeliverable("iTerm session id is not a bare UUID")
        return 0
    if args.dry_run:
        plan = ("ESC->" if esc_first else "") + "/reload-plugins --force"
        print(f"DRY_RUN would fire {plan} at iTerm session {uuid} after {args.delay}s")
        return 0
    _fire(_build_osascript(uuid, args.delay, esc_first=esc_first))
    print("RELOAD_FIRED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
