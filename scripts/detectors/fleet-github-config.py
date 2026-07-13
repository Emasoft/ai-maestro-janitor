#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""fleet-github-config — SURFACE the daemon's fleet GitHub-config findings (TRDD-157OH2D7).

The EXPENSIVE part — probing ~13 ai-maestro plugin repos over the GitHub API for missing
branch rulesets, `required_linear_history` (which BLOCKS Claude's merges), missing CI gates,
etc. — runs ONCE machine-wide in the daemon's `github-config-audit` task (issue #7:
fleet-scope work is the daemon's single-writer job; N sessions each probing 13 repos would
stampede the API). This per-session detector is the CHEAP half: it reads ONLY the daemon's
`<global-state>/github-config-findings.json` (one file read + a content-hash dedupe) and makes
ZERO `gh` calls, so a fire costs almost nothing.

It emits ONE compact drift line naming the finding counts by class, and ALWAYS ends it with a
pointer to `/janitor-github-config-fix` — the janitor can only NOTIFY the main Claude, so the
notification must carry the remedy (the user's explicit requirement). Content-hash dedupe means
an unchanged finding set never re-nags; a repo getting fixed (or a NEW gap appearing) changes
the digest and re-alerts exactly once.

Silent when: the daemon has not written a findings file yet, the file is empty/unreadable, or
there are no findings. Read-only: it never calls the API and never mutates a repo — the
on-demand fix skill does that, only on the user's confirmation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import github_config_audit as gca  # noqa: E402
import global_state as gs  # noqa: E402
import state  # noqa: E402

_NAME = "fleet-github-config"


def main() -> int:
    if not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_FLEET_GITHUB_CONFIG_ENABLED", True):
        return 0
    state.init_state()

    findings_file = gs.global_state_dir() / gca.FINDINGS_FILENAME
    try:
        payload = json.loads(findings_file.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        # No audit written yet (daemon hasn't run its 6h beat), or unreadable → silent.
        return 0

    line = gca.summarize(payload)
    if line is None:
        return 0

    # Dedupe on the finding-SET digest, not the rendered line: the wording could change
    # across versions without the actual gaps changing, and we don't want that to re-nag.
    # A genuine change (repo fixed / new gap) shifts the digest and re-alerts exactly once.
    #
    # No sanitize_for_drift_line here: `summarize` emits ONLY the fixed finding vocabulary +
    # integer counts + the fixed fix-skill pointer — no slug, no untrusted text reaches the
    # line — so defanging would only mangle the `[github-config]` label for nothing.
    seen = state.state_dir() / "fleet-github-config-seen.txt"
    out = dedupe.emit_once(seen, gca.findings_digest(payload), line)
    if out is not None:
        print(out)

    state.rotate_log_if_big(_NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
