#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Backing script for /janitor-reload-plugins (analogue of compact_trigger.py).

Fires a DETACHED, delayed ESC -> /reload-plugins at THIS session's own iTerm pane
so the agent can pick up freshly auto-updated plugin hooks/skills WITHOUT the
human typing the command. The heartbeat's `[janitor-reload]` marker asks the
agent to "silently run /reload-plugins", but the Skill tool refuses built-in
slash commands — so, exactly like the compact trigger, the only working path is
to type the command into this session's own pane via osascript.

UNLIKE the compact trigger there is NO resume directive: /reload-plugins reloads
plugin code in place and does NOT discard the conversation, so nothing needs to
be recorded for an auto-resume — the turn simply continues after the reload.

The delay + detach are load-bearing: the script must NOT be killed by the very
ESC it sends, so it returns immediately and the keystrokes fire ~delay seconds
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

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import terminal_trigger  # noqa: E402

# An iTerm session id is a hex UUID (8-4-4-4-12). $ITERM_SESSION_ID is
# `<tty>:<UUID>`. We interpolate the UUID into an `osascript -e` string, so we
# MUST reject anything that isn't hex+dashes — an env var is attacker-settable,
# and a value like `x:" then do shell script "rm -rf ~" --` would otherwise
# inject AppleScript. A security plugin must not ship its own injection sink.
_UUID_RE = re.compile(r"^[0-9A-Fa-f-]{8,64}$")


def _build_osascript(uuid: str, delay_s: float) -> str:
    """AppleScript that targets ONLY the session whose id == uuid, then ESC -> /reload-plugins.

    `write text (character id 27) without newline` sends a raw ESC byte (clears any
    half-typed input / interrupts an in-flight turn). After a short settle,
    `write text "/reload-plugins"` types and submits the command (iTerm's write
    text appends a return)."""
    return (
        f"delay {delay_s}\n"
        'tell application "iTerm2"\n'
        "  repeat with w in windows\n"
        "    repeat with t in tabs of w\n"
        "      repeat with s in sessions of t\n"
        f'        if (id of s) is "{uuid}" then\n'
        "          tell s\n"
        "            write text (character id 27) without newline\n"
        "            delay 0.6\n"
        '            write text "/reload-plugins"\n'
        "          end tell\n"
        "        end if\n"
        "      end repeat\n"
        "    end repeat\n"
        "  end repeat\n"
        "end tell\n"
    )


def _fire(script: str) -> None:
    """Launch osascript fully detached so the parent returns before its own ESC."""
    subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        ["osascript", "-e", script],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Self-trigger /reload-plugins at this session's pane.")
    ap.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="seconds to wait before sending ESC -> /reload-plugins (lets the turn settle)",
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
    sent = terminal_trigger.send_self_command("/reload-plugins", delay_s=args.delay, dry_run=args.dry_run)
    if sent != terminal_trigger.USE_ITERM_PATH:
        if sent.startswith("FIRED:"):
            print("RELOAD_FIRED")
        elif sent.startswith("DRY_RUN:"):
            print(f"DRY_RUN {sent.split(':', 1)[1]}")
        else:  # NO_AUTO_TERMINAL:<kind> — can't auto-send; ask the human (legacy marker)
            print("NO_ITERM")
        return 0

    iterm = os.environ.get("ITERM_SESSION_ID", "").strip()
    if not iterm:
        print("NO_ITERM")
        return 0
    uuid = iterm.split(":")[-1].strip()
    if not _UUID_RE.match(uuid):
        # Malformed / untrusted session id — refuse to build the osascript rather
        # than risk AppleScript injection. The skill asks the user to reload manually.
        print(f"BAD_ITERM_ID {uuid[:32]}", file=sys.stderr)
        print("NO_ITERM")
        return 0
    if args.dry_run:
        print(f"DRY_RUN would fire ESC->/reload-plugins at iTerm session {uuid} after {args.delay}s")
        return 0
    _fire(_build_osascript(uuid, args.delay))
    print("RELOAD_FIRED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
