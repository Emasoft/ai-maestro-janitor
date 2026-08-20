#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""gh-reply-watch — notify the main Claude when someone REPLIES to a thread this project opened.

OWNER DIRECTIVE (2026-08-02): "the job of detecting if someone posted a new issue on the
project repo and to track the github posts made by the current active project main claude
and regularly check and reports if there are replies, must be a chore executed always by
the janitor. no need to enable it. […] integrate it better in the chron. ensure it works
both inside ai-maestro harness and outside."

This is the CRON half of the GH-reply monitor. The polling itself is unchanged — it is
`scripts/gh_issues_monitor/gh_notify_poll.py`, whose `do_poll` was ALREADY a one-shot
(poll once, print, write the cursor, exit). The retired `/janitor-github-issues-monitor-on`
skill only wrapped that one-shot in a `while true; sleep 120` inside a session-scoped
`Monitor`, which is why the feature died on every restart and compaction and had to be
re-armed by hand. A detector is the same poll on the heartbeat's schedule, so it survives
restarts, needs no agent to start it, and runs in BOTH runtime backends — a hook cannot
call the `Monitor` tool, but every backend fires the heartbeat.

Distinct from `github-issues-watch`, which reports NEW issues on THIS project's own repo.
This one reports REPLIES to threads this project opened, on ANY repo. Different question,
different mechanism, no shared state.

FAIL-OPEN everywhere: `gh` missing / unauthenticated / rate-limited, a network error, or a
poller crash all mean "silently do nothing". A notification feature must never be able to
break the heartbeat.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import gh_notify_inbox  # noqa: E402  # the fleet-wide inbox SSOT (TRDD-079778RM)
import global_state as gs  # noqa: E402
import state  # noqa: E402

_POLLER = Path(__file__).resolve().parent.parent / "gh_issues_monitor" / "gh_notify_poll.py"
_DETECTOR = "gh-reply-watch"

# Machine-wide poll floor (janitor#215). The 900s per-project interval was reasoned
# against GitHub's `X-Poll-Interval: 60` response for `GET /notifications` — correct
# for ONE session, but that header is scoped to the ACCOUNT/token, and every janitor
# instance on this machine shares the one owner identity. On a host running N
# concurrent projects the AGGREGATE poll rate is N/900 req/s, unbounded as N grows —
# at 13 projects that already sits at ~87% of the 60/hour floor. This stamp makes the
# interval bound the ACCOUNT's poll rate rather than each project's: only one fire,
# machine-wide, may actually call `gh` within any `_GLOBAL_MIN_INTERVAL_S` window. The
# same mechanism `marketplace-op.lock` already uses to globalise bulk refreshes
# (`global_state.py`'s `control_dir()`), applied here as a rate stamp rather than a
# mutual-exclusion lock — concurrent fires from different projects are meant to
# interleave, just not all poll in the same second.
_GLOBAL_MIN_INTERVAL_S = 60
_GLOBAL_STAMP_TASK = "gh-reply-watch-global-poll"


def _global_gate_allows(now: int) -> bool:
    """True iff no other project's fire has polled `gh` within the floor window.

    Read-then-write is not a lock — two fires racing within the same instant can both
    pass — but the worst case is a small, bounded overshoot, never the unbounded N/900
    aggregate the per-project-only interval allowed. Matches the fail-open posture of
    every other chore here: a missed poll costs a delayed notification, not a broken
    heartbeat.
    """
    return (now - gs.read_last_run(_GLOBAL_STAMP_TASK)) >= _GLOBAL_MIN_INTERVAL_S


def _mark_global_poll(now: int) -> None:
    try:
        state.atomic_write(gs.last_run_path(_GLOBAL_STAMP_TASK), str(now))
    except OSError:
        pass  # best-effort — a failed stamp only means the NEXT fire may poll early


def _poll_argv(*args: str) -> list[str]:
    """Invoke the poller the way everything else does — `uv run --script`, never directly.

    The poller is NOT chmod +x (unlike a detector, which dispatch and CI execute by path),
    so `[str(_POLLER)]` is a `permission denied` at runtime — a fail-open detector would
    have swallowed that forever and simply never reported a reply. Verified against the
    real file mode, and it matches how the skills have always called it.
    """
    return ["uv", "run", "--script", "--quiet", str(_POLLER), *args]


def _poller_state_dir() -> Path | None:
    """Where the poller keeps `registry.json` + the `state.json` cursor, or None.

    Asked of the poller itself (`--state-dir`) rather than recomputed here: it owns a
    legacy-location migration, and a second implementation of that path is a second
    thing to keep in step.
    """
    proc = state.run_subprocess(
        _poll_argv("--state-dir"),
        detector_name=_DETECTOR,
    )
    if proc is None or proc.returncode != 0:
        return None
    path = (proc.stdout or "").strip()
    return Path(path) if path else None


def main() -> int:
    state.init_state()

    # The only gate. Default TRUE: this is a chore the janitor always runs.
    if not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_GH_REPLY_WATCH_ENABLED", True):
        return 0

    sdir = _poller_state_dir()
    if sdir is None:
        # The poller could not even report its own state dir — treat as unavailable.
        return 0

    # THE INBOX LANE (TRDD-079778RM). When the daemon has recently published the
    # account's notifications, read those instead of competing for the poll token: the
    # list is ACCOUNT-scoped and so identical for every project, while the registry that
    # filters it is per-project. No `gh` call means no floor to respect, so EVERY armed
    # project gets served on EVERY fire — which is the actual fix. Under the old
    # first-come token, 40 armed projects produced 3 non-deferred polls in the entire log.
    #
    # FAIL-OPEN: no inbox, a stale one (daemon down, chore absorbed by the ai-maestro
    # server), or a corrupt one all fall through to the original gated path below, so this
    # can never make the lane worse than it was.
    now = int(time.time())
    inbox_extra: list[str] = []
    if gh_notify_inbox.is_fresh(now):
        inbox_extra = ["--from-inbox"]
    else:
        # The machine-wide floor (janitor#215): both the baseline call below and the real
        # poll a few lines down issue a `gh api notifications` request, so the gate sits
        # BEFORE either — checking it only in front of the real poll would still let every
        # project's first-fire baseline call through uncapped.
        if not _global_gate_allows(now):
            state.log_line(
                _DETECTOR,
                "deferred — machine-wide poll floor not yet elapsed (janitor#215)",
            )
            return 0
        _mark_global_poll(now)

    # FIRST FIRE: adopt the current notification state and say NOTHING. The retired
    # enable-skill ran `--baseline` as its step 1 for exactly this reason. Without it the
    # first poll on a project would replay every already-read thread that happens to be
    # in the registry as if it were a fresh reply.
    if not (sdir / "state.json").exists():
        state.run_subprocess(_poll_argv("--baseline", *inbox_extra), detector_name=_DETECTOR)
        state.log_line(_DETECTOR, "first fire — baselined the notification cursor, reporting from the next fire")
        state.rotate_log_if_big(_DETECTOR)
        return 0

    proc = state.run_subprocess(_poll_argv(*inbox_extra), detector_name=_DETECTOR)
    if proc is None or proc.returncode != 0:
        # gh missing / not authed / rate-limited / offline. Stay silent: this is a
        # notification feature, not a broken-tooling alarm on every fire. (The poller
        # itself surfaces a DEGRADED line once on stdout when it can distinguish the
        # cause, which the loop below prints like any other line.)
        state.log_line(_DETECTOR, "poller unavailable — skipping this fire")
        return 0

    for raw in (proc.stdout or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        # SANITIZE EVERY LINE. The poller interpolates GitHub-controlled text — the issue
        # TITLE and the replying comment BODY — and its `squeeze()` only collapses
        # whitespace and truncates; it does not defang anything. That was harmless while
        # this output went to Monitor notifications a human reads, but these lines are now
        # heartbeat drift that the MODEL acts on, and a bare `[janitor-...]` line there is
        # an instruction. So an issue titled `[janitor-self-disarm]` must arrive defanged,
        # exactly as github-issues-watch already does via `issues_watch.format_drift`.
        safe = state.sanitize_for_drift_line(line)
        print(safe)
        state.log_line(_DETECTOR, safe)

    state.rotate_log_if_big(_DETECTOR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
