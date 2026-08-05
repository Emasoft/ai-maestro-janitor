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

It emits ONE compact drift line about THIS PROJECT'S REPO ONLY, and ALWAYS ends it with a
pointer to `/janitor-github-config-fix --slug <this repo>` — the janitor can only NOTIFY the
main Claude, so the notification must carry the remedy (the user's explicit requirement).
PER-PROJECT CHANNELING (user directive 2026-07-17): findings about OTHER repos never reach
this session — not even as counts. A session in repo A has the wrong skills and token budget
for repo B, is forbidden from acting on another agent's workdir/repo, and would become a
data-exfiltration surface into projects with weaker protections. Repos with no live session
reach the HUMAN via the daemon's notification channel (TRDD-4649ZLE0), never another project.
Content-hash dedupe is scoped to THIS repo's finding set: an unchanged set never re-nags, and
another repo's fix can neither re-alert nor silence this session.

Silent when: the daemon has not written a findings file yet, the file is empty/unreadable,
this project has no resolvable GitHub slug, or THIS repo is clean. Read-only: it never calls
the API and never mutates a repo — the on-demand fix skill does that, only on confirmation.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import env_detect  # noqa: E402
import github_config_audit as gca  # noqa: E402
import global_state as gs  # noqa: E402
import issue_catalog  # noqa: E402
import state  # noqa: E402

_NAME = "fleet-github-config"


def _current_slug() -> str:
    """This project's `owner/repo`, from its origin remote. Cheap — no network, no `gh`."""
    proc = state.run_subprocess(
        ["git", "remote", "get-url", "origin"],
        timeout=5,
        cwd=state.project_root(),
        detector_name=_NAME,
    )
    if proc is None or proc.returncode != 0:
        return ""
    return env_detect.github_slug((proc.stdout or "").strip()) or ""


def _propose_for_this_repo(payload: object) -> None:
    """Raise GHCFG-001 for THIS repo's drift only — never for the rest of the fleet.

    The audit covers ~13 plugin repos, but a proposal TRDD is a file in the CURRENT repo's
    git-tracked design board. Authoring one there about a DIFFERENT repository would litter a project
    with tasks that do not belong to it — the same instinct the cross-project rule encodes: you do not
    reach into someone else's tree, and you do not leave your work in it either. The other repos are
    still NOTIFIED (the summary line above names them and carries the fix skill); they get their own
    proposal in their own board when the janitor next fires there.
    """
    if not isinstance(payload, dict):
        return
    slug = _current_slug()
    if not slug:
        return
    mine = sorted(
        {
            str(f.get("code"))
            for f in payload.get("findings", [])
            if isinstance(f, dict) and f.get("slug") == slug and f.get("code")
        }
    )
    if not mine:
        # The fleet has drift, but not in OUR repo — so if we proposed one before, it is fixed now.
        # (The `summarize() is None` path only covers a fleet that is clean EVERYWHERE; without this,
        # a repo fixed while any other repo is still broken would keep its stale proposal forever.)
        issue_catalog.clear_issue("GHCFG-001", where=slug)
        return
    r = issue_catalog.raise_issue(
        "GHCFG-001",
        where=slug,
        evidence=[f"github:{slug}"],
        slug=slug,
        detail=", ".join(mine),
    )
    if r.first_seen and r.line:
        print(r.line)
    elif not r.ok:
        state.log_line(_NAME, f"could not raise GHCFG-001: {r.why}")


#: Where ai-maestro publishes its own copy when it has absorbed `github-config-audit`
#: (janitor#197). It cannot write into our state dir — that project has a standing owner
#: directive that its only writes are `~/.aimaestro` and `~/agents` — so the consumer has to
#: reach across instead. Wire-identical payload: same FINDING_CODES, same shape, same
#: tri-state silence rules, and the population is parsed from OUR marketplace catalog rather
#: than their constants (theirs covered 10 of 14 repos, so a partial audit could have stamped
#: the chore done while four repos went unaudited).
def _server_findings_path() -> Path:
    """Resolved at CALL time, not import time, so `$HOME` redirection actually takes effect —
    a module-level `Path.home()` would bake in the real home before a test could move it, and
    the suite runs this detector as a subprocess precisely to keep the real machine untouched."""
    return Path.home() / ".aimaestro" / gca.FINDINGS_FILENAME


def _load(path: Path) -> dict | None:
    """Parse one findings file, or None when absent/unreadable/not an object."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _read_findings() -> dict | None:
    """The freshest fleet-audit payload: ours, or the server's when it owns the chore.

    Ordering is by `generated_at`, NOT by a liveness check on the server. Whoever ran the
    audit most recently is the one with something to say, and that keeps the read honest in
    both handover directions — a server that just took the chore over has the newer file, and
    a server that has stopped running it stops winning by default the moment our daemon's next
    beat lands. Deciding on liveness instead would let a live-but-idle server's stale audit
    permanently mask a fresher local one, which is the same class of bug as gating the daemon's
    exit on `server_is_alive()` rather than on the chore claim (#134).

    A malformed or missing file on either side simply loses; it never suppresses the other.
    """
    candidates = [p for p in (_load(gs.global_state_dir() / gca.FINDINGS_FILENAME),
                              _load(_server_findings_path())) if p is not None]
    if not candidates:
        return None
    # `generated_at` is ISO-8601 UTC from both writers, so lexical order is chronological.
    return max(candidates, key=lambda p: str(p.get("generated_at", "")))


def main() -> int:
    if not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_FLEET_GITHUB_CONFIG_ENABLED", True):
        return 0
    state.init_state()

    payload = _read_findings()
    if payload is None:
        # No audit written yet (neither the daemon's 6h beat nor a server), or unreadable → silent.
        return 0

    # PER-PROJECT CHANNELING: everything below is scoped to THIS repo's slug. No slug ⇒
    # surface NOTHING (an unattributable session must never receive another repo's data).
    slug = _current_slug()
    if not slug:
        return 0

    line = gca.summarize_for_slug(payload, slug)
    if line is None:
        # THIS repo is clean (whatever the rest of the fleet looks like) — withdraw any
        # standing proposal so the board never carries a problem that has been fixed.
        issue_catalog.clear_issue("GHCFG-001", where=slug)
        return 0

    _propose_for_this_repo(payload)

    # Dedupe on THIS repo's finding-SET digest, not the rendered line or the fleet set:
    # wording changes never re-nag, a genuine change in OUR repo re-alerts exactly once,
    # and another repo's fix/break can neither re-alert nor silence this session.
    #
    # No sanitize_for_drift_line here: `summarize_for_slug` emits only the fixed finding
    # vocabulary + counts + the fix-skill pointer, and the slug is shape-validated by its
    # _SLUG_RE fullmatch before it can reach the line — defanging would mangle it for nothing.
    seen = state.state_dir() / "fleet-github-config-seen.txt"
    out = dedupe.emit_once(seen, gca.findings_digest(gca.payload_for_slug(payload, slug)), line)
    if out is not None:
        print(out)

    state.rotate_log_if_big(_NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
