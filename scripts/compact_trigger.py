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
import cold_cache_compact  # noqa: E402  -- GUARD 2 (TRDD-PH8SAQKS): harness_will_autocompact
import state  # noqa: E402  -- GUARD 1 (TRDD-4JEBTT2C): reads last-compact.ts
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

# pre-compact-handoff.py's own `_LAST_TRIGGER_FILENAME`, mirrored here (not imported — that hook
# script is not a library) so the two literals can never drift apart silently; a test pins the
# two constants equal (YM65RCZA item 3).
PRECOMPACT_LAST_TRIGGER_FILENAME = "precompact-last-trigger.json"


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

    # GUARD 1 (TRDD-4JEBTT2C, issue 306, review round 2): capture the compaction high-water
    # marks AT THE DECISION -- this script's own invocation IS the decision, made by the caller
    # (Stop hook / heartbeat phase) the instant it saw a large idle context. The detached sender
    # below can still defer minutes on a busy pane; passing these baselines lets it tell "a
    # compaction already landed since we decided to send" apart from "still pending".
    #
    # TWO stamps, not one (round-2 finding). `last-compact.ts` alone is too LATE a signal: it is
    # written by the PostCompact hook AFTER the compaction finishes, and in the incident that
    # was ~111s after the harness's own auto-compact STARTED (14:28:46 vs. PostCompact at
    # 14:30:37) -- for that whole window this guard would have seen `current == baseline` and
    # let the queued send through. `precompact-last-trigger.json` is written by
    # pre-compact-handoff.py (`_LAST_TRIGGER_FILENAME`, same literal name hardcoded below to
    # avoid importing a hook script as a library) at compaction START, on EVERY PreCompact
    # firing -- closing that window. `read_landed_stamp` (terminal_trigger.py) reads it via its
    # `written_at` float field -- `time.time()` epoch seconds (pre-compact-handoff.py:1151/1163),
    # the same base `last-compact.ts` uses, so the two baselines are directly comparable. (A
    # DIFFERENT `written_at` field, an ISO string, exists in this same source file at line 872 --
    # that one belongs to `precompact-continuity.json`, a different stamp this guard does not
    # read; do not conflate the two if this comment is ever re-derived from that file.)
    #
    # Two residual risks, disclosed rather than fixed here (review round 2): (i) `read_landed_stamp`
    # reads a corrupted/mid-write JSON stamp as 0.0 -- always BELOW a real baseline, so it can
    # never cause a false cancel, but a stamp write that failed or raced at land-time could be
    # misread as "nothing landed" and let a stale send through; the write itself goes through
    # `state.atomic_write` (rename-on-write), so a torn read requires disk-level corruption, not
    # a race -- accepted. (ii) `precompact-last-trigger.json` is ONE file per project state dir,
    # not per-session -- two concurrent sessions in the same project would cancel each other's
    # queued /compact on an unrelated compaction. That is an over-cancellation (a send that would
    # have been fine gets skipped), the SAFE direction for a guard whose whole job is "don't send
    # blind" -- accepted, not fixed.
    #
    # Path resolution deliberately uses `state.state_dir()`, not this script's own
    # `_project_root()`-built path: `state` (imported for GUARD 1 above) resolves
    # CLAUDE_PROJECT_DIR -> a process-local override -> `git rev-parse` -> cwd, while
    # `_project_root()` here has no override step. The two can only disagree when
    # CLAUDE_PROJECT_DIR is unset AND something upstream in THIS process set the override before
    # `state` was imported -- not reachable in this script today -- but reusing `state.state_dir()`
    # makes the two paths agree BY CONSTRUCTION rather than by that argument, and it is the exact
    # path `post-compact-resume.py` (guard 4) and `pre-compact-handoff.py` write through.
    _sd = state.state_dir()
    _last_compact_path = _sd / state.LAST_COMPACT_STAMP
    _last_trigger_path = _sd / PRECOMPACT_LAST_TRIGGER_FILENAME  # pre-compact-handoff.py's _LAST_TRIGGER_FILENAME
    for _stamp_path, _stamp_kind in ((_last_compact_path, "int"), (_last_trigger_path, "json_written_at")):
        if not _stamp_path.is_file():
            state.log_line("compact-trigger", f"compact guard: no {_stamp_path.name} at {_stamp_path} — baseline 0")
    landed_baseline = [
        (str(_last_compact_path), float(state.read_int_state(_last_compact_path, 0)), "int"),
        # Reuses terminal_trigger's own reader rather than a second JSON-parsing copy of it
        # (both must agree on what "landed" means, or the baseline and the land-time recheck
        # inside run_verified_send could silently disagree).
        (str(_last_trigger_path), terminal_trigger.read_landed_stamp(_last_trigger_path, "json_written_at"), "json_written_at"),
    ]

    # GUARD 2 (TRDD-PH8SAQKS, issue 306, round 2): this is the ONE caller that measures context
    # itself, BEFORE any floor gate (`min_context_tokens()`) has narrowed it -- unlike the
    # dispatch/hook callers of this script, which only ever invoke it once `ctx` has already
    # climbed above that floor (see `cold_cache_compact.harness_will_autocompact`'s own
    # docstring for why those two sites were found to be permanently unreachable and unwired).
    # `--dry-run` still measures and logs but does not itself send anything either way, so the
    # guard runs unconditionally rather than being skipped under --dry-run.
    #
    # EXEMPT `--hard` (review round 3): the guard's own band can sit BELOW the >=85% emergency
    # trip point on a small window -- e.g. a 200k CLAUDE_CODE_AUTO_COMPACT_WINDOW gives an
    # effective point of ~166k, a band of roughly [158k, 166k + HARNESS_BACKSTOP_MARGIN), and
    # the 85% trip fires at 170k, squarely inside it -- which would suppress the one path this
    # script exposes specifically to be urgent (ESC-interrupt NOW, never enqueue-and-wait). A
    # caller reaching for `--hard` has already decided the send cannot wait for the harness;
    # guard 2 exists to avoid a REDUNDANT compact, not to override an explicit urgency signal.
    # `--hard` currently has no automated caller (the >=85% PreToolUse hook that used to pass it
    # was removed, TRDD-11GAS4LC/7MGJYLY5 -- see this file's own commented history above) but the
    # flag remains a manual/skill-invocable escape hatch, so the exemption still matters.
    if args.hard:
        state.log_line("compact-trigger", "compact guard 2: --hard emergency path, guard skipped")
    else:
        # Prefer the caller's own session transcript when given: the project's NEWEST transcript
        # can belong to a different live session of the same project, so measuring it would
        # judge this session's compact by another session's context size.
        _ctx = cold_cache_compact.context_tokens_for(
            args.transcript_path or cold_cache_compact.newest_transcript(state.project_root())
        )
        if cold_cache_compact.harness_will_autocompact(_ctx):
            print(cold_cache_compact.GUARD2_STDOUT_MARKER)
            return 0

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
            abort_if_landed=landed_baseline,
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
