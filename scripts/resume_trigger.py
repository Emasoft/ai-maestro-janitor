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
later. It targets ONLY this session's own pane (tmux via process ancestry, or iTerm
via `terminal_trigger.send_self_command`) — never other panes — so concurrent Claude
instances are untouched.

When no channel can be driven (no tmux pane, no iTerm session id), self-trigger
isn't available: the script prints NO_ITERM and the cron path resumes as usual.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import terminal_trigger  # noqa: E402

# The slash-command typed into the pane. A FIXED module constant (never user/env
# input), so interpolating it into the tmux/osascript send is not an injection sink.
RESUME_CMD = "/janitor-resume"


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
    ap.add_argument(
        "--transcript-path",
        default=None,
        help=(
            "this session's own transcript (the PostCompact hook's own `transcript_path`) — "
            "session-scopes the ESC-interrupt cooldown check so two live sessions of the same "
            "project never share one (see terminal_trigger.inject_until_sent)"
        ),
    )
    args = ap.parse_args()

    # SELF-CANCEL when there is nothing to resume (user report 2026-07-17: repeated
    # `/janitor-resume` typed into the pane long after the session had resumed). The
    # flags this command exists to consume are `resume-after-compact.flag` /
    # `rate-limited.flag`; when NEITHER is present at fire time (the cron fire beat
    # this push to the consumption, or a second compaction fired a second push), a
    # typed `/janitor-resume` is pure queue spam — it would sit behind the current
    # turn and run as a visible no-op later. Fail-open: an unresolvable project dir
    # must not kill the push (typing a redundant command is annoying; missing a real
    # resume strands an unattended session).
    pending_flags: list[str] = []
    try:
        import state  # noqa: PLC0415 -- sibling lib, resolved via the path insert above

        sdir = state.state_dir()
        pending_flags = [
            str(sdir / f) for f in ("resume-after-compact.flag", "rate-limited.flag")
        ]
        if not any(Path(p).is_file() for p in pending_flags):
            print("NOTHING_PENDING")
            return 0
    except Exception:  # noqa: BLE001 -- fail-open toward firing
        pending_flags = []  # unresolvable project dir ⇒ no guard either (fire unconditionally)

    # send_self_command drives both tmux and iTerm directly (TRDD-db169d9e R3); only a
    # channel it cannot resolve at all falls through to NO_ITERM below.
    # esc_first=False ALWAYS: SOFT is the only correct mode post-compaction.
    # `abort_unless_any` is the TYPE-TIME half of the self-cancel (TRDD-DXM75JB2): the
    # fire-time check above stays as the cheap no-subprocess early exit; the child
    # re-checks the same flags after its delay, so a heartbeat fire consuming them
    # DURING the sleep no longer gets a redundant `/janitor-resume` typed after it.
    #
    # NO PRESENCE CANCEL (owner directive 2026-08-02, migrated here 2026-08-13 — janitor#257).
    # This used to refuse outright when the user looked present, on the theory that "a present
    # user IS the resume". That theory is wrong in the case this exists for: a user sitting at
    # the keyboard reading a compacted session is not resuming anything, and the refusal was
    # terminal — the resume flag stays pending with nothing left to fire it. Presence now DEFERS
    # at the pane instead (8 s per keystroke, never stops trying), so a resume typed into a busy
    # pane lands a few seconds late rather than never. `abort_unless_any` remains the correct
    # cancel here, and it cancels on the RIGHT evidence: the flags being gone means some other
    # path already resumed, which presence never implied.
    with terminal_trigger.scoped_transcript_path_env(args.transcript_path):
        sent = terminal_trigger.send_self_command(
            RESUME_CMD, delay_s=args.delay, esc_first=False, dry_run=args.dry_run,
            abort_unless_any=pending_flags or None,
            respect_user_presence=False,
        )
    if sent.startswith("FIRED:"):
        print("RESUME_FIRED")
    elif sent.startswith("DRY_RUN:"):
        print(f"DRY_RUN {sent.split(':', 1)[1]}")
    else:  # no channel this module can drive — can't auto-send; the cron path resumes instead
        print("NO_ITERM")
    return 0


if __name__ == "__main__":
    sys.exit(main())
