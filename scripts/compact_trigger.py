#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Backing script for /janitor-compact-context (TRDD-31095269).

Records the resume directive, then fires a DETACHED, delayed ESC -> /compact at
THIS session's own iTerm pane so the agent can compact its own context mid-session
(native auto-compact is unreliable on the 1M window).

Two steps:
  1. If a directive is supplied, write it to
     <project>/.janitor/state/resume-directive.txt (atomically). The PostCompact
     hook consumes it during the compaction and the next heartbeat emits
     "[janitor-resume] <directive>", so the session auto-resumes exactly where it
     left off. (No directive -> the PostCompact hook falls back to the newest
     in-flight TRDD on the board.)
  2. Launch a detached osascript that, after a short delay, sends ESC (to
     interrupt an in-flight turn) then "/compact" to the iTerm session whose id
     matches the UUID in $ITERM_SESSION_ID.

The delay + detach are load-bearing: the script must NOT be killed by the very
ESC it sends, so it returns immediately and the keystrokes fire ~delay seconds
later (after the agent ends its turn). It targets ONLY the session whose UUID
matches $ITERM_SESSION_ID — never other panes — so concurrent Claude instances
are untouched.

Outside iTerm ($ITERM_SESSION_ID unset) self-trigger isn't available: the script
prints NO_ITERM and the skill asks the user to run /compact manually.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import terminal_trigger  # noqa: E402

# An iTerm session id is a hex UUID (8-4-4-4-12). $ITERM_SESSION_ID is
# `<tty>:<UUID>`. We interpolate the UUID into an `osascript -e` string, so we
# MUST reject anything that isn't hex+dashes — an env var is attacker-settable,
# and a value like `x:" then do shell script "rm -rf ~" --` would otherwise
# inject AppleScript. A security plugin must not ship its own injection sink.
_UUID_RE = re.compile(r"^[0-9A-Fa-f-]{8,64}$")

# The slash-commands the three modes type into the pane. These are FIXED module
# constants (never user/env input), so interpolating them into the tmux/osascript
# send is not an injection sink (unlike the UUID, which is validated above).
COMPACT_CMD = "/compact"
HANDOFF_CMD = "/janitor-write-handoff"
# In HARD --handoff the detached sender can't observe when the handoff skill finishes,
# so the ordering is delegated to the skill: it writes the handoff then, seeing this
# arg, chains to /compact itself. In SOFT --handoff no chaining is needed — both
# commands are enqueued and the input queue serialises them (handoff turn, then compact).
HANDOFF_THEN_COMPACT_CMD = "/janitor-write-handoff --then-compact"


def plan_compact(*, soft: bool, handoff: bool) -> tuple[list[str], bool]:
    """Map the (--soft, --handoff) flags to the (commands, esc_first) send plan.

    Four modes, each a keystroke sequence typed into this session's own pane:
      - default (hard):    ESC → /compact                     (interrupt now, compact)
      - --soft:            /compact                            (no ESC → runs at turn end)
      - --handoff (hard):  ESC → /janitor-write-handoff …      (skill then chains /compact)
      - --handoff --soft:  /janitor-write-handoff, /compact    (no ESC → both enqueued)

    Returns (commands, esc_first). `esc_first=False` is the SOFT contract: omit the ESC
    so the agent's in-flight turn is NOT interrupted — the command(s) enqueue and run
    only once the turn ends, losing no work.
    """
    if handoff and soft:
        return [HANDOFF_CMD, COMPACT_CMD], False
    if handoff:
        return [HANDOFF_THEN_COMPACT_CMD], True
    if soft:
        return [COMPACT_CMD], False
    return [COMPACT_CMD], True


def _project_root() -> Path:
    """Mirror lib.state._resolve_project_root so resume-directive.txt lands exactly
    where post-compact-resume.py reads it: CLAUDE_PROJECT_DIR -> git toplevel -> cwd."""
    explicit = os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
    if explicit:
        return Path(explicit)
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(out.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd()


def _write_directive(directive: str) -> Path:
    """Atomically write the one-shot resume pointer the PostCompact hook consumes."""
    sd = _project_root() / ".janitor" / "state"
    sd.mkdir(parents=True, exist_ok=True)
    target = sd / "resume-directive.txt"
    tmp = target.with_name(f"{target.name}.tmp.{os.getpid()}")
    tmp.write_text(directive + "\n", encoding="utf-8")
    os.replace(tmp, target)
    return target


def _build_osascript(
    uuid: str, delay_s: float, *, commands: Sequence[str] = (COMPACT_CMD,), esc_first: bool = True
) -> str:
    """AppleScript that targets ONLY the session whose id == uuid, then (optionally) a
    raw ESC followed by each command typed and submitted.

    `esc_first=True` (default) writes a raw ESC byte first
    (`write text (character id 27)`), interrupting an in-flight turn so the command runs
    NOW — the HARD path. `esc_first=False` (SOFT) sends NO ESC, so the command is typed
    while the agent is mid-turn and Claude Code enqueues it until the turn ends. Each
    command in `commands` is typed via `write text "<cmd>"` (iTerm appends a return), so
    a two-command list enqueues both in order. The commands are FIXED module constants
    (never user/env input), so interpolating them is not an injection sink — unlike
    `uuid`, which `_UUID_RE` validates before it reaches here.
    """
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
        lines.append("            write text (character id 27) without newline")
        lines.append("            delay 0.6")
    for i, command in enumerate(commands):
        if i:
            lines.append("            delay 0.4")  # let each enqueued command register
        lines.append(f'            write text "{command}"')
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


def main() -> int:
    ap = argparse.ArgumentParser(description="Record a resume directive then self-trigger /compact.")
    ap.add_argument(
        "--directive",
        default="",
        help="one-line continuation note recorded for post-compact auto-resume",
    )
    ap.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="seconds to wait before sending ESC -> /compact (lets the turn settle)",
    )
    ap.add_argument(
        "--soft",
        action="store_true",
        help="do NOT press ESC — enqueue the command(s) so they run AFTER the current "
        "turn ends (no in-flight work lost); default is a hard ESC-interrupt compact",
    )
    ap.add_argument(
        "--handoff",
        action="store_true",
        help="run /janitor-write-handoff (a rich agent-authored handoff) BEFORE /compact "
        "— for delicate junctures; combinable with --soft",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="write the directive + print the plan, but do NOT fire osascript (for tests)",
    )
    args = ap.parse_args()

    directive = args.directive.strip()
    if directive:
        path = _write_directive(directive)
        print(f"DIRECTIVE_WRITTEN {path}")

    commands, esc_first = plan_compact(soft=args.soft, handoff=args.handoff)

    # Prefer a non-iTerm automatable terminal (tmux) when detected via process
    # ancestry. iTerm / unknown / not-yet-automated terminals return USE_ITERM_PATH
    # and fall through to the proven iTerm-osascript path below (TRDD-db169d9e R3).
    sent = terminal_trigger.send_self_command(
        commands, delay_s=args.delay, esc_first=esc_first, dry_run=args.dry_run
    )
    if sent != terminal_trigger.USE_ITERM_PATH:
        if sent.startswith("FIRED:"):
            print("COMPACT_FIRED")
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
        # than risk AppleScript injection. The directive is still recorded above,
        # so the skill can ask the user to /compact manually.
        print(f"BAD_ITERM_ID {uuid[:32]}", file=sys.stderr)
        print("NO_ITERM")
        return 0
    if args.dry_run:
        plan = ("ESC->" if esc_first else "") + "->".join(commands)
        print(f"DRY_RUN would fire {plan} at iTerm session {uuid} after {args.delay}s")
        return 0
    _fire(_build_osascript(uuid, args.delay, commands=commands, esc_first=esc_first))
    print("COMPACT_FIRED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
