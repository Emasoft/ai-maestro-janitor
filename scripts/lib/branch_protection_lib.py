"""Branch-protection ruleset helpers — shared between the Tier 1 user-invoked
skill (`/janitor-branch-protection-setup`) and the Tier 2 guarded auto path
(`scripts/guard/branch_protection_apply.py`).

Per TRDD-631fa3de §10:

* The baseline ruleset is the same in both surfaces. Single source of truth
  here.
* All `gh` calls use a fixed argv (no shell). Failures surface verbatim, no
  half-apply.
* Refuses on non-default branch, non-admin viewer, missing repo.
* Idempotent: callers check `is_baseline_present()` before posting.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

# Baseline name — the ruleset is recognised by exact name match so the
# idempotency check in is_baseline_present() doesn't get confused by
# user-authored rulesets sitting alongside ours.
BASELINE_RULESET_NAME = "janitor-baseline"

# JSON payload for `gh api POST /repos/{owner}/{repo}/rulesets`. Pinned to
# the same rule set the Tier 1 skill displays. The "ref_name" target is
# overridden per-call to point at the discovered default branch.
def baseline_ruleset_payload(default_branch: str) -> dict:
    """Return the baseline ruleset JSON for the named default branch.

    Rules (least-privilege defaults for a typical small-repo workflow):
      * `non_fast_forward` — block force-pushes.
      * `deletion`         — block branch deletion.
      * `required_linear_history` — fast-forward / squash merges only.
      * `pull_request`     — every change reaches main via a PR with
                              ≥1 review and a dismissable-stale-reviews
                              policy. Required approvers count is left
                              at 1 because higher requires a team and
                              is not a sensible default.

    Deliberately omitted from the baseline (the user can layer on top):
      * required_status_checks — needs status-check names the janitor
        does not know; surface to the user instead.
      * required_signatures — high bar; opt-in.
      * required_deployments / required_status — same.
    """
    if not default_branch:
        raise ValueError("default_branch must be a non-empty string")
    return {
        "name": BASELINE_RULESET_NAME,
        "target": "branch",
        "enforcement": "active",
        "conditions": {
            "ref_name": {
                "include": [f"refs/heads/{default_branch}"],
                "exclude": [],
            },
        },
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {"type": "required_linear_history"},
            {
                "type": "pull_request",
                "parameters": {
                    "required_approving_review_count": 1,
                    "dismiss_stale_reviews_on_push": True,
                    "require_code_owner_review": False,
                    "require_last_push_approval": False,
                    "required_review_thread_resolution": True,
                },
            },
        ],
    }


_REPO_RE = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")


def detect_repo_slug(plugin_root: Path) -> str | None:
    """Read `repository` from `.claude-plugin/plugin.json` and return
    the `owner/repo` slug. Returns None when the manifest is missing,
    unparseable, or the URL doesn't match a github.com repo."""
    manifest = plugin_root / ".claude-plugin" / "plugin.json"
    if not manifest.is_file():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    url = str(data.get("repository", "") or "")
    m = re.match(r"^https?://github\.com/([^/]+/[^/]+?)(?:\.git)?/?$", url)
    if not m:
        return None
    slug = m.group(1)
    return slug if _REPO_RE.match(slug) else None


def gh_available() -> bool:
    return shutil.which("gh") is not None


def detect_default_branch(slug: str) -> str | None:
    """Ask gh for the repo's default branch. Returns None on failure."""
    if not gh_available():
        return None
    try:
        proc = subprocess.run(
            ["gh", "api", f"repos/{slug}", "--jq", ".default_branch"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    name = (proc.stdout or "").strip()
    return name or None


def viewer_is_admin(slug: str) -> bool:
    """Best-effort: True iff the authenticated viewer has admin perms
    on `slug`. Used as a safety gate before posting a ruleset — if we
    can't administer, we can't fix.
    """
    if not gh_available():
        return False
    try:
        proc = subprocess.run(
            ["gh", "api", f"repos/{slug}", "--jq", ".permissions.admin"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if proc.returncode != 0:
        return False
    return (proc.stdout or "").strip().lower() == "true"


def list_existing_rulesets(slug: str) -> list[dict] | None:
    """Return the ruleset list for `slug`, or None on failure."""
    if not gh_available():
        return None
    try:
        proc = subprocess.run(
            ["gh", "api", f"repos/{slug}/rulesets"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, list) else None


def is_baseline_present(slug: str) -> bool | None:
    """Idempotency check — True iff a ruleset named BASELINE_RULESET_NAME
    is already attached to the repo. Returns None on lookup failure so
    the caller knows the answer is "unknown" rather than "no" (which
    matters for the auto path — don't act when uncertain)."""
    rulesets = list_existing_rulesets(slug)
    if rulesets is None:
        return None
    return any(
        isinstance(r, dict) and r.get("name") == BASELINE_RULESET_NAME
        for r in rulesets
    )


def create_baseline_ruleset(slug: str, default_branch: str,
                            ) -> tuple[bool, str]:
    """POST the baseline ruleset. Returns (success, message).

    `message` is either the new ruleset id (on success) or the trimmed
    `gh` stderr (on failure) — the caller decides whether to log /
    surface that.
    """
    payload = baseline_ruleset_payload(default_branch)
    if not gh_available():
        return (False, "gh CLI not in PATH")
    try:
        proc = subprocess.run(
            [
                "gh", "api", "--method", "POST",
                f"repos/{slug}/rulesets",
                "--input", "-",
            ],
            input=json.dumps(payload),
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return (False, f"gh subprocess failed: {exc}")
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().splitlines()[-1:] or ["gh exited non-zero"]
        return (False, err[0])
    # Extract the new ruleset id if the response is JSON.
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return (True, "created")
    new_id = data.get("id")
    return (True, f"id={new_id}" if new_id is not None else "created")


def guard_mode_enabled() -> bool:
    """Master gate for the Tier 2 auto path. Default is False — the
    user must explicitly enable per-project."""
    val = os.environ.get("CLAUDE_PLUGIN_OPTION_GUARD_MODE_ENABLED", "")
    return val.strip().lower() in ("1", "true", "yes", "on")
