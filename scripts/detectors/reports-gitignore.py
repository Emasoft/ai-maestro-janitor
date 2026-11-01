#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""reports-gitignore — keep `reports_dev/` OUT of git (TRDD-KSUIEPTQ; TRDD-WP7TCRME Rule 3).

Owner rule 2026-11-01: `reports/` is git-tracked project content, sanitized with the
`sanitize-reports` CLI before it is committed; `reports_dev/` holds raw and private material
(absolute home paths, usernames, hostnames, credentials caught in a pasted log), must be
gitignored, and its contents are never deleted. Earlier versions of this detector required
`reports/` to be gitignored too; it no longer does. It also does NOT undo the lines it wrote
before: it never edits or removes an existing `/reports/` line and says nothing about one —
removing it would expose reports written under the old private regime as untracked files, one
`git add -A` from a public push.

It is a FIXING detector and surfaces a line only when:

  * it ADDED `/reports_dev/` to the user's `.gitignore` — reported once, because a silent edit
    to a tracked file is worse than a noisy one, and they need to review and commit the diff;
  * `reports_dev/` is unignored AND already has TRACKED files — the decision-margin case the
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
            f"[{_NAME}] {names} was NOT gitignored — added the entries. Raw reports carry "
            "absolute paths, usernames and secrets caught in logs, and a report pushed to a "
            "public repo cannot be unpublished. Review the .gitignore diff and commit it.",
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
