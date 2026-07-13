#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Backing script for /janitor-resume (analogue of reload_trigger.py) — TRDD-HI0BGQGJ.

Fires a DETACHED, delayed `/janitor-resume` at THIS session's own pane so an idle
session that just compacted (or was rate-limited) picks its work back up WITHOUT
waiting for the next heartbeat cron fire. That fire is the ONLY thing that wakes an
idle REPL, and its latency is bounded by the currently-armed cadence — up to 30 min
at the SLOW `*/30` floor. This push closes that gap: it types the resume command
now, so the resume happens in seconds.

`/janitor-resume` runs the dispatcher stub, which re-enters the EXISTING
dispatch.py `_phase_compact_resume` (the flag consumer). So this trigger adds NO
resume logic of its own — it only makes the session run the same code the cron
would have run, sooner.

SOFT (no ESC) is the ONLY mode here (unlike reload/compact, which expose --hard):
a compaction has ALREADY ended the turn, so there is no in-flight turn to interrupt
— an ESC would be pointless and, if a native auto-compact kept the turn alive, would
needlessly cut it. The command enqueues and runs at the (already-reached) turn
boundary.

The delay + detach are load-bearing: the caller (the PostCompact hook) must return
immediately, so the script returns at once and the keystrokes fire ~delay seconds
later. It targets ONLY the session whose UUID matches $ITERM_SESSION_ID (or the tmux
pane via process ancestry) — never other panes — so concurrent Claude instances are
untouched.

Outside an automatable terminal ($ITERM_SESSION_ID unset and not tmux) self-trigger
isn't available: the script prints NO_ITERM and the cron path resumes as usual.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import terminal_trigger  # noqa: E402

# The slash-command typed into the pane. A FIXED module constant (never user/env
# input), so interpolating it into the tmux/osascript send is not an injection sink.
RESUME_CMD = "/janitor-resume"

# An iTerm session id is a hex UUID (8-4-4-4-12). $ITERM_SESSION_ID is
# `<tty>:<UUID>`. We interpolate the UUID into an `osascript -e` string, so we
# MUST reject anything that isn't hex+dashes — an env var is attacker-settable,
# and a value like `x:" then do shell script "rm -rf ~" --` would otherwise
# inject AppleScript. A security plugin must not ship its own injection sink.
_UUID_RE = re.compile(r"^[0-9A-Fa-f-]{8,64}$")


def _build_osascript(uuid: str, delay_s: float) -> str:
    """AppleScript that targets ONLY the session whose id == uuid, then types
    `/janitor-resume` (SOFT — no ESC).

    There is deliberately no `esc_first` here: a compaction already ended the turn,
    so `/janitor-resume` is typed into the idle prompt and submitted (iTerm's
    `write text` appends a return). The command is a FIXED module constant, so
    interpolating it is not an injection sink — unlike `uuid`, which `_UUID_RE`
    validates before it reaches here.
    """
    lines = [
        f"delay {delay_s}",
        'tell application "iTerm2"',
        "  repeat with w in windows",
        "    repeat with t in tabs of w",
        "      repeat with s in sessions of t",
        f'        if (id of s) is "{uuid}" then',
        "          tell s",
        f'            write text "{terminal_trigger.applescript_quote(RESUME_CMD)}"',
        "          end tell",
        "        end if",
        "      end repeat",
        "    end repeat",
        "  end repeat",
        "end tell",
    ]
    return "\n".join(lines) + "\n"


def _fire(script: str) -> None:
    """Launch osascript fully detached so the parent returns immediately."""
    subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        ["osascript", "-e", script],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Self-trigger /janitor-resume at this session's pane.")
    ap.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="seconds to wait before typing /janitor-resume (lets the REPL settle post-compact)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan, but do NOT fire osascript (for tests)",
    )
    args = ap.parse_args()

    # Prefer a non-iTerm automatable terminal (tmux) when detected via process
    # ancestry. iTerm / unknown / not-yet-automated terminals return USE_ITERM_PATH
    # and fall through to the proven iTerm-osascript path below (TRDD-db169d9e R3).
    # esc_first=False ALWAYS: SOFT is the only correct mode post-compaction.
    sent = terminal_trigger.send_self_command(
        RESUME_CMD, delay_s=args.delay, esc_first=False, dry_run=args.dry_run
    )
    if sent != terminal_trigger.USE_ITERM_PATH:
        if sent.startswith("FIRED:"):
            print("RESUME_FIRED")
        elif sent.startswith("DRY_RUN:"):
            print(f"DRY_RUN {sent.split(':', 1)[1]}")
        else:  # NO_AUTO_TERMINAL:<kind> — can't auto-send; the cron path resumes instead
            print("NO_ITERM")
        return 0

    iterm = os.environ.get("ITERM_SESSION_ID", "").strip()
    if not iterm:
        print("NO_ITERM")
        return 0
    uuid = iterm.split(":")[-1].strip()
    if not _UUID_RE.match(uuid):
        # Malformed / untrusted session id — refuse to build the osascript rather
        # than risk AppleScript injection. The cron path resumes instead.
        print(f"BAD_ITERM_ID {uuid[:32]}", file=sys.stderr)
        print("NO_ITERM")
        return 0
    if args.dry_run:
        print(f"DRY_RUN would fire {RESUME_CMD} at iTerm session {uuid} after {args.delay}s")
        return 0
    _fire(_build_osascript(uuid, args.delay))
    print("RESUME_FIRED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
