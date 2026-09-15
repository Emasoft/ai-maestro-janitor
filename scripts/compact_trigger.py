#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Backing script for /janitor-compact-context (TRDD-31095269).

Records the resume directive, then fires a DETACHED, delayed /compact at
THIS session's own pane (tmux or iTerm, via `terminal_trigger.send_self_command`)
so the agent can compact its own context mid-session (native auto-compact is
unreliable on the 1M window).

Two steps:
  1. If a directive is supplied, write it to
     <project>/.janitor/state/resume-directive.txt (atomically). The PostCompact
     hook consumes it during the compaction and the next heartbeat emits
     "[janitor-resume] <directive>", so the session auto-resumes exactly where it
     left off. (No directive -> the PostCompact hook falls back to the newest
     in-flight TRDD on the board.)
  2. `send_self_command` launches a detached, verified sender that, after a short
     delay, types "/compact" into this session's own tmux/iTerm pane. SOFT is
     the default (TRDD-0GPQROC1): no ESC, so the command enqueues and runs when
     the current turn ends — no in-flight work lost. `--hard` sends ESC first
     (interrupt NOW) for emergencies like the >=85% enforcement hook.

The delay + detach are load-bearing: the script must NOT be killed by the ESC it
may send, so it returns immediately and the keystrokes fire ~delay seconds
later (after the agent ends its turn). It targets ONLY this session's own pane
— never other panes — so concurrent Claude instances are untouched.

When no channel can be driven (no tmux pane, no iTerm session id), self-trigger
isn't available: the script prints NO_ITERM and the skill asks the user to run
/compact manually.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import terminal_trigger  # noqa: E402

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
    """Map the resolved (soft, handoff) mode to the (commands, esc_first) send plan.

    Four modes, each a keystroke sequence typed into this session's own pane
    (since TRDD-0GPQROC1 soft is the CLI default and --hard is the opt-in):
      - soft (default):    /compact                            (no ESC → runs at turn end)
      - --hard:            ESC → /compact                      (interrupt now, compact)
      - --handoff (soft):  /janitor-write-handoff, /compact    (no ESC → both enqueued)
      - --handoff --hard:  ESC → /janitor-write-handoff …      (skill then chains /compact)

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
        # Read-only: GIT_OPTIONAL_LOCKS=0 so this never takes .git/index.lock
        # and collides with a concurrent `publish.py` commit (janitor#245).
        git_env = dict(os.environ)
        git_env["GIT_OPTIONAL_LOCKS"] = "0"
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
            env=git_env,
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
        help="press ESC first — interrupt the in-flight turn so /compact runs NOW; "
        "for emergencies (context near the wall), e.g. the >=85%% enforcement hook",
    )
    ap.add_argument(
        "--handoff",
        action="store_true",
        help="run /janitor-write-handoff (a rich agent-authored handoff) BEFORE /compact "
        "— for delicate junctures; combinable with --hard",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="write the directive + print the plan, but do NOT fire osascript (for tests)",
    )
    ap.add_argument(
        "--resolve-timeout",
        type=float,
        default=terminal_trigger.DEFAULT_AIMAESTRO_RESOLVE_TIMEOUT_S,
        metavar="SECONDS",
        help="cap on the one SYNCHRONOUS step of the ai-maestro send (the `list --json` that "
        "finds this agent's tmux session); everything after it is detached. Lower it when the "
        "CALLER is itself under a hard deadline — a registered hook budget — so this inner "
        "bound nests strictly inside it instead of outliving it (AM8JD9SG F9). Expiring early "
        "is safe: it degrades to the local tmux keystroke path.",
    )
    ap.add_argument(
        "--transcript-path",
        default=None,
        help=(
            "this session's own transcript (e.g. the Stop hook's `transcript_path`) — "
            "session-scopes the ESC-interrupt cooldown check so two live sessions of the same "
            "project never share one (see terminal_trigger.inject_until_sent)"
        ),
    )
    args = ap.parse_args()

    directive = args.directive.strip()
    if directive:
        path = _write_directive(directive)
        print(f"DIRECTIVE_WRITTEN {path}")

    # SOFT is the default (TRDD-0GPQROC1): the skill ends its turn right after firing,
    # so the enqueued /compact runs seconds later anyway — without risking an ESC that
    # cuts in-flight work. --hard restores the ESC for the emergency path (the >=85%
    # context-enforcement hook passes it explicitly).
    commands, esc_first = plan_compact(soft=not args.hard, handoff=args.handoff)

    # send_self_command drives both tmux and iTerm directly (TRDD-db169d9e R3); only a
    # channel it cannot resolve at all falls through to NO_ITERM below.
    # NO PRESENCE CANCEL (owner directive 2026-08-02, migrated here 2026-08-13 — janitor#257).
    # A compact injection IS the most destructive of the four — which is an argument for waiting
    # until the field is empty, not for abandoning it. The pane-level injector does exactly that
    # (empty field required, stop on the first keystroke, retry 8 s later, never give up), so the
    # half-typed prompt this cancel was protecting is already protected, and protected better:
    # the old cancel left an over-full context un-compacted with no retry, which is how a session
    # reaches the ~999k wall where `/compact` itself can no longer run.
    with terminal_trigger.scoped_transcript_path_env(args.transcript_path):
        sent = terminal_trigger.send_self_command(
            commands,
            delay_s=args.delay,
            esc_first=esc_first,
            dry_run=args.dry_run,
            respect_user_presence=False,
            aimaestro_resolve_timeout_s=args.resolve_timeout,
        )
    if sent.startswith("FIRED:"):
        print("COMPACT_FIRED")
    elif sent.startswith("DRY_RUN:"):
        print(f"DRY_RUN {sent.split(':', 1)[1]}")
    else:  # no channel this module can drive, or a present user — can't auto-send; ask the human
        print("NO_ITERM")
    return 0


if __name__ == "__main__":
    sys.exit(main())
