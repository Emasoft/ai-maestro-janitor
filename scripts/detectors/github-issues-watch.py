#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""github-issues-watch — notify the main Claude of new issues / new comments (TRDD-2KQQAEPP).

USER order (2026-07-03): a command to enable monitoring of the open/new issues on the
project's GitHub repo, notifying the main Claude of new issues or new messages on the
tracker.

ALWAYS ON since the 2026-08-02 owner directive ("must be a chore executed always by the
janitor. no need to enable it"). The opt-in sentinel `.janitor/state/issues-watch.flag` is
RETIRED — a per-feature switch is the silent-disable shape the 2026-07-31 directive removed,
because a project sitting un-watched looks identical to a healthy one from the outside. The
only remaining gate is the standard opt-out knob, so arm/disarm stays the real switch.

The seen-map `{number: updatedAt}` is the dedupe: GitHub bumps `updatedAt` when a COMMENT
lands, so the one field catches both a NEW issue and a NEW message on an existing one, and
an issue that has not moved since the last pass never re-fires.

FIRST FIRE IS SILENT. The retired enable-command seeded a baseline BEFORE arming the flag,
and its skill called that ordering load-bearing; removing the flag without keeping the
seeding would make the first fire on every repo diff against an empty map and report the
ENTIRE open backlog into the model's context. So a MISSING seen-map means "adopt the
current state, say nothing" — and the test is `exists()`, never the parsed value, because a
CORRUPT map must keep reporting (see `_read_seen`).

FAIL-OPEN everywhere: no git remote, a non-GitHub remote, `gh` missing / unauthenticated /
rate-limited, a network error, or unparseable JSON all mean "silently do nothing". A
notification feature must never be able to break the heartbeat.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import issues_watch  # noqa: E402
import state  # noqa: E402

_SEEN = "issues-watch-seen.json"
_LIMIT = 50


def _read_seen(path: Path) -> dict[str, str]:
    """The persisted seen-map. Fail-open to {} — which is the SAFE direction only because
    the enable command seeds a baseline: a lost map re-reports the currently-open issues
    once, it never silently swallows a new one."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def main() -> int:
    state.init_state()
    sd = state.state_dir()

    # The only gate left. Default TRUE: this is a chore the janitor always runs.
    if not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_ISSUES_WATCH_ENABLED", True):
        return 0

    project_root = state.project_root()

    remote = state.run_subprocess(
        ["git", "remote", "get-url", "origin"],
        cwd=str(project_root),
        detector_name="github-issues-watch",
    )
    if remote is None or remote.returncode != 0:
        return 0
    slug = issues_watch.parse_remote_slug(remote.stdout or "")
    if slug is None:
        state.log_line("github-issues-watch", "origin is not a GitHub remote — skipping")
        return 0

    proc = state.run_subprocess(
        [
            "gh", "issue", "list",
            "--repo", slug,
            "--state", "open",
            "--json", "number,title,updatedAt,comments,url",
            "--limit", str(_LIMIT),
        ],
        cwd=str(project_root),
        detector_name="github-issues-watch",
    )
    if proc is None or proc.returncode != 0:
        # gh missing / not authed / rate-limited / offline. Stay silent: the user opted
        # into a notification, not into a broken-tooling alarm on every fire.
        state.log_line("github-issues-watch", "gh issue list unavailable — skipping this fire")
        return 0

    current = issues_watch.parse_issues(proc.stdout or "")
    seen_path = sd / _SEEN

    # FIRST FIRE ON THIS PROJECT: adopt the current open set as the baseline and say
    # NOTHING. Without this, going always-on would dump every open issue of every repo
    # into context the first time the detector runs there — the flood the retired
    # /janitor-issues-watch-on prevented by seeding before it armed the flag.
    #
    # Keyed on exists(), NOT on the parsed map: `_read_seen` fails open to {} for a
    # CORRUPT file too, and for that case re-reporting is the deliberately safe
    # direction. Treating a corrupt map as "first run" would silently swallow whatever
    # arrived while it was broken.
    if not seen_path.exists():
        state.atomic_write(seen_path, json.dumps(issues_watch.baseline(current), indent=0))
        state.log_line(
            "github-issues-watch",
            f"first fire for {slug} — baselined {len(current)} open issue(s), reporting from the next fire",
        )
        state.rotate_log_if_big("github-issues-watch")
        return 0

    seen = _read_seen(seen_path)

    for issue, reason in issues_watch.diff_issues(seen, current):
        print(issue_line := issues_watch.format_drift(issue, reason, state.sanitize_for_drift_line))
        state.log_line("github-issues-watch", issue_line)

    # Rewrite the map AFTER reporting, from the current open set. Closed issues drop out;
    # a reopened one legitimately reads as "new" next time.
    state.atomic_write(seen_path, json.dumps(issues_watch.baseline(current), indent=0))
    state.rotate_log_if_big("github-issues-watch")
    return 0


if __name__ == "__main__":
    sys.exit(main())
