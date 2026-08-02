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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import state  # noqa: E402

_POLLER = Path(__file__).resolve().parent.parent / "gh_issues_monitor" / "gh_notify_poll.py"
_DETECTOR = "gh-reply-watch"


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

    # FIRST FIRE: adopt the current notification state and say NOTHING. The retired
    # enable-skill ran `--baseline` as its step 1 for exactly this reason. Without it the
    # first poll on a project would replay every already-read thread that happens to be
    # in the registry as if it were a fresh reply.
    if not (sdir / "state.json").exists():
        state.run_subprocess(_poll_argv("--baseline"), detector_name=_DETECTOR)
        state.log_line(_DETECTOR, "first fire — baselined the notification cursor, reporting from the next fire")
        state.rotate_log_if_big(_DETECTOR)
        return 0

    proc = state.run_subprocess(_poll_argv(), detector_name=_DETECTOR)
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
