#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""reports-gitignore — keep `reports/` and `reports_dev/` OUT of git (TRDD-WP7TCRME Rule 3).

Every agent, skill, hook and scan on this machine writes reports under `<repo>/reports/`, and
those reports routinely carry absolute home paths, usernames, internal hostnames, proprietary
source, and credentials caught in a pasted log. The invariant that both dirs are gitignored was
a hard rule NOTHING enforced — each project was expected to remember two lines, and a project
that forgets does not find out until the leak is already pushed.

This is a FIXING detector, not a reporting one (Rule 3): where the entries are missing it adds
them, because "your report directory is not ignored" has exactly one defensible answer.

It surfaces a line in only two cases, and is silent otherwise:

  * it CHANGED the user's `.gitignore` — reported once, because a silent edit to a tracked file
    is worse than a noisy one, and they need to review and commit the diff;
  * a report dir is unignored AND already has TRACKED files — the decision-margin case the
    library deliberately refuses to auto-resolve (a gitignore line would hide the finding
    without untracking anything, and a leak that already reached a public remote needs rotation,
    not an ignore rule).

Silent when everything is already correct, and silent when git cannot answer — an indeterminate
probe is not actionable and must not nag. Project-scoped; never touches another repo. Always
exits 0.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import reports_gitignore  # noqa: E402
import state  # noqa: E402

_NAME = "reports-gitignore"


def main() -> int:
    state.init_state()
    root = state.project_root()

    added, _ok, needs_human = reports_gitignore.ensure_ignored(root)
    seen = state.state_dir() / f"{_NAME}-seen.txt"

    if added:
        names = ", ".join(f"{d}/" for d in sorted(added))
        # Keyed on WHAT was added, so a later regression (someone deletes the lines) re-reports
        # rather than being suppressed by a stale key from the first time.
        line = dedupe.emit_once(
            seen,
            f"added:{names}",
            f"[{_NAME}] {names} was NOT gitignored — added the entries. Reports carry absolute "
            "paths, usernames and secrets caught in logs, and a report pushed to a public repo "
            "cannot be unpublished. Review the .gitignore diff and commit it.",
        )
        if line is not None:
            print(line)

    if needs_human:
        line = dedupe.emit_once(
            seen,
            "tracked:" + ",".join(sorted(needs_human)),
            reports_gitignore.format_finding(needs_human),
        )
        if line is not None:
            print(line)

    state.rotate_log_if_big(_NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
