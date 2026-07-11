#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""github-issues-watch — notify the main Claude of new issues / new comments (TRDD-2KQQAEPP).

USER order (2026-07-03): a command to enable monitoring of the open/new issues on the
project's GitHub repo, notifying the main Claude of new issues or new messages on the
tracker — "off by default, but once enabled it continue reporting until it is disabled."

OFF BY DEFAULT. The whole detector is one `stat` of the opt-in sentinel
`.janitor/state/issues-watch.flag` (written by `/janitor-issues-watch-on`) and returns
immediately when it is absent — so a project that never opted in pays nothing on every
fire. When ON it keeps reporting until `/janitor-issues-watch-off` removes the sentinel.

The seen-map `{number: updatedAt}` is the dedupe: GitHub bumps `updatedAt` when a COMMENT
lands, so the one field catches both a NEW issue and a NEW message on an existing one, and
an issue that has not moved since the last pass never re-fires.

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

_FLAG = "issues-watch.flag"
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

    # The opt-in gate. One stat, then out — this is what keeps a non-watching project at
    # ~zero cost on every heartbeat fire.
    if not (sd / _FLAG).is_file():
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
