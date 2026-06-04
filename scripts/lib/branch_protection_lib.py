"""Branch-protection ruleset helpers — shared between the Tier 1 user-invoked
skill (`/janitor-branch-protection-setup`) and the Tier 2 guarded auto path
(`scripts/guard/branch_protection_apply.py`).

Per TRDD-631fa3de §10 + the ratified unified baseline
(janitor #14 / maintainer #7):

* The baseline is the SAME pair of rulesets in both surfaces. Single
  source of truth here, byte-identical with the maintainer plugin.
* All `gh` calls use a fixed argv (no shell). Failures surface verbatim,
  no half-apply.
* Refuses on non-default branch, non-admin viewer, missing repo.
* Idempotent-by-name: callers PATCH a ruleset whose name already exists,
  else POST a new one.

## The ratified two-ruleset baseline

Both `target: branch`, `enforcement: active`, condition
`ref_name.include: ["~DEFAULT_BRANCH"]` (the GitHub magic ref that
resolves to whatever branch the repo declares as default at apply
time — NOT `refs/heads/<name>`; this is what makes the JSON byte-
identical and portable across repos that use main/master/custom):

1. ``baseline-history-protect`` — ``bypass_actors: []`` (nobody bypasses
   history protection). Rules: ``deletion``, ``non_fast_forward``,
   ``required_linear_history``.
2. ``baseline-pr-and-checks`` — ``bypass_actors`` grants the repo-admin
   role (``actor_id: 5``) an ``always`` bypass so a solo admin is not
   locked out of their own repo by the self-approval requirement.
   Rules: ``pull_request`` (1 approval, dismiss-stale, thread-resolution)
   + ``required_status_checks`` (strict policy; CI check contexts are
   AUTO-DETECTED at apply time — see ``detect_required_status_checks``).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import yaml

# The two ratified ruleset names. Recognised by exact name match so the
# idempotent-apply logic in branch_protection_apply.py PATCHes the right
# ruleset instead of POSTing a duplicate, and so we don't clobber
# user-authored rulesets sitting alongside ours.
HISTORY_RULESET_NAME = "baseline-history-protect"
PR_CHECKS_RULESET_NAME = "baseline-pr-and-checks"

# Every pre-ratification ruleset name in the COMBINED lineage of BOTH the janitor
# and the maintainer-agent plugins — the shared orphan-delete UNION agreed on
# janitor#14 / maintainer#7. The apply path deletes ALL of these by EXACT NAME once
# the ratified baseline-* pair is confirmed in place, so a repo either plugin ever
# touched converges to EXACTLY {baseline-history-protect, baseline-pr-and-checks}
# with no straggler left behind. Name-based ONLY — we NEVER delete a ruleset we did
# not create (that would nuke an owner's own custom ruleset). This list MUST stay
# byte-identical to the maintainer plugin's union so whichever applies last fully
# converges the repo.
LEGACY_RULESET_NAMES: tuple[str, ...] = (
    # janitor lineage
    "janitor-baseline",                  # janitor v0.5.x single ruleset
    "main-hardening",                    # janitor live split-pair (manual, pre-rename)
    "main-ci-gate",                      # janitor live split-pair (manual, pre-rename)
    # maintainer-agent lineage (workflow-protect-branch, pre-ratification)
    "default-branch-ruleset",
    "default-branch-no-force-no-delete",
    "default-branch-required-checks",
)
# Back-compat alias: some callers/tests import the singular legacy name.
LEGACY_RULESET_NAME = LEGACY_RULESET_NAMES[0]

# The GitHub magic ref that resolves to the repo's default branch at apply
# time. Using this (instead of refs/heads/<name>) keeps the payload byte-
# identical to the maintainer plugin and portable across default-branch
# names — the ratified spec mandates it.
_DEFAULT_BRANCH_REF = "~DEFAULT_BRANCH"

# The repo-admin RepositoryRole id. GitHub assigns stable numeric ids to
# the built-in roles; 5 == admin. Granted an `always` bypass on the
# PR/checks ruleset so a solo admin can still merge their own work.
_ADMIN_REPOSITORY_ROLE_ID = 5


def baseline_ruleset_payloads(
    default_branch: str,
    required_status_checks: list[dict] | None = None,
) -> list[dict]:
    """Return the ratified pair of baseline ruleset payloads.

    Each element is a JSON-serialisable dict ready for
    `gh api {POST|PUT} /repos/{owner}/{repo}/rulesets`.

    `default_branch` is accepted for signature symmetry with the rest of
    the module and to fail loudly on an empty value, but the emitted
    `conditions.ref_name.include` uses the `~DEFAULT_BRANCH` magic ref
    (NOT `refs/heads/<default_branch>`) — that is what the ratified spec
    and the maintainer plugin emit, so the payloads are byte-identical
    regardless of the literal branch name.

    `required_status_checks` is the auto-detected list of
    `{"context": "<job-id>"}` dicts (see
    `detect_required_status_checks`). When None or empty, the PR/checks
    ruleset ships an empty `required_status_checks` list — the rule is
    still present (strict policy on) but gates on no specific contexts
    until the repo's CI surfaces some.
    """
    if not default_branch:
        raise ValueError("default_branch must be a non-empty string")
    checks = list(required_status_checks or [])
    history_protect = {
        "name": HISTORY_RULESET_NAME,
        "target": "branch",
        "enforcement": "active",
        "conditions": {
            "ref_name": {
                "include": [_DEFAULT_BRANCH_REF],
                "exclude": [],
            },
        },
        "bypass_actors": [],
        "rules": [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {"type": "required_linear_history"},
        ],
    }
    pr_and_checks = {
        "name": PR_CHECKS_RULESET_NAME,
        "target": "branch",
        "enforcement": "active",
        "conditions": {
            "ref_name": {
                "include": [_DEFAULT_BRANCH_REF],
                "exclude": [],
            },
        },
        "bypass_actors": [
            {
                "actor_id": _ADMIN_REPOSITORY_ROLE_ID,
                "actor_type": "RepositoryRole",
                "bypass_mode": "always",
            },
        ],
        "rules": [
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
            {
                "type": "required_status_checks",
                "parameters": {
                    "strict_required_status_checks_policy": True,
                    "required_status_checks": checks,
                },
            },
        ],
    }
    return [history_protect, pr_and_checks]


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


def ruleset_id_by_name(slug: str, name: str) -> int | None:
    """Return the numeric id of the ruleset named `name`, or None.

    None means BOTH "lookup failed" and "no such ruleset" — the caller
    must distinguish those via `list_existing_rulesets` returning None
    when it needs the don't-act-when-uncertain behaviour. This helper is
    a convenience for the apply path's PATCH-vs-POST decision once the
    list lookup has already succeeded.
    """
    rulesets = list_existing_rulesets(slug)
    if rulesets is None:
        return None
    for r in rulesets:
        if isinstance(r, dict) and r.get("name") == name:
            rid = r.get("id")
            if isinstance(rid, int):
                return rid
    return None


def baselines_present(slug: str) -> bool | None:
    """True iff BOTH ratified rulesets are already attached to the repo.

    Returns None on lookup failure so the caller knows the answer is
    "unknown" rather than "no" (matters for the auto path — don't act
    when uncertain). Used for the cheap "already converged" short-circuit
    before doing any PATCH/POST work.
    """
    rulesets = list_existing_rulesets(slug)
    if rulesets is None:
        return None
    names = {r.get("name") for r in rulesets if isinstance(r, dict)}
    return HISTORY_RULESET_NAME in names and PR_CHECKS_RULESET_NAME in names


def _workflow_triggers(wf: dict) -> set[str]:
    """The set of event names in a workflow's ``on:`` trigger.

    LOAD-BEARING: GitHub's ``on:`` key parses as the YAML 1.1 boolean ``True``
    under PyYAML, so we look it up under BOTH ``True`` and the literal ``"on"`` —
    without the ``True`` lookup ``wf.get("on")`` is ``None`` and EVERY workflow
    would be (wrongly) treated as having no PR trigger, dropping every check.
    Byte-identical to the maintainer-agent plugin's `triggers()` (janitor#14 /
    maintainer cde65eb) so both plugins auto-detect the SAME contexts."""
    on = wf.get(True, wf.get("on"))
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return set(on)
    if isinstance(on, dict):
        return set(on.keys())
    return set()


def detect_required_status_checks(project_root: Path) -> list[dict]:
    """Discover the repo's CI check contexts from its WORKFLOW FILES.

    Globs ``.github/workflows/*.yml`` and ``*.yaml`` under `project_root`,
    parses each, and returns a sorted, de-duplicated list of
    ``{"context": "<name>"}`` dicts — the EXACT shape the GitHub rulesets
    API wants for ``required_status_checks``. The context for a job is its
    ``name:`` if set, else the job id (matching how GitHub names a check
    when no display name is given).

    Why parse the CONFIGURED workflow jobs rather than query the runtime
    ``repos/{slug}/commits/{branch}/check-runs`` API (the previous
    approach):

    * Runtime check-runs are EMPTY on a fresh repo whose CI has never run
      — so the ruleset would ship with no required checks until the first
      push, defeating the purpose of protecting the very first PR.
    * Worse, check-run NAMES do not always equal the context GitHub uses
      for branch-protection matching; feeding the wrong contexts to the
      rulesets API gets the whole POST/PATCH rejected with **HTTP 422
      Validation Failed**, which fails the entire apply. The workflow-
      config job ids/names are the source of truth GitHub itself derives
      the contexts from.

    This is the cross-plugin-agreed source (janitor #14) and matches the
    maintainer plugin's documented approach.

    Never raises and never hard-codes job ids: a malformed/unreadable
    workflow file is skipped (not fatal), and a project with no workflows
    (or all unparseable) yields an empty list — the ruleset is still
    created with a ``required_status_checks`` rule that gates on no
    specific contexts.
    """
    workflows_dir = project_root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return []
    files = sorted(workflows_dir.glob("*.yml")) + sorted(workflows_dir.glob("*.yaml"))
    contexts: set[str] = set()
    for wf_path in files:
        try:
            wf = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            # A single broken/unreadable workflow must never crash the
            # applier — skip it and keep collecting from the rest.
            continue
        if not isinstance(wf, dict):
            continue
        # Only a PR-triggered workflow can produce a check on a PR. A push-only
        # workflow's jobs (release / notify / tag-deploy) NEVER report on a PR, so
        # requiring one as a required_status_checks context would wedge every
        # non-admin PR forever in "expected, not reported" (admins bypass — which is
        # exactly why it's invisible on a 1-person repo). Filter to PR-triggered
        # workflows only — the shared fix coordinated on janitor#14 / maintainer
        # cde65eb; both plugins MUST detect the same set to stay byte-identical.
        if not ({"pull_request", "pull_request_target"} & _workflow_triggers(wf)):
            continue
        jobs = wf.get("jobs", {})
        if not isinstance(jobs, dict):
            continue
        for job_id, job_cfg in jobs.items():
            name = (job_cfg.get("name") if isinstance(job_cfg, dict) else None) or job_id
            if isinstance(name, str) and name.strip():
                contexts.add(name.strip())
    return [{"context": ctx} for ctx in sorted(contexts)]


def _post_or_patch_ruleset(
    slug: str, payload: dict, existing_id: int | None,
) -> tuple[bool, str]:
    """POST a new ruleset, or PATCH an existing one when `existing_id` is
    set (idempotent-by-name). Returns (success, message)."""
    if not gh_available():
        return (False, "gh CLI not in PATH")
    if existing_id is None:
        argv = [
            "gh", "api", "--method", "POST",
            f"repos/{slug}/rulesets",
            "--input", "-",
        ]
        verb = "created"
    else:
        argv = [
            "gh", "api", "--method", "PATCH",
            f"repos/{slug}/rulesets/{existing_id}",
            "--input", "-",
        ]
        verb = "updated"
    try:
        proc = subprocess.run(
            argv,
            input=json.dumps(payload),
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return (False, f"gh subprocess failed: {exc}")
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().splitlines()[-1:] or ["gh exited non-zero"]
        return (False, err[0])
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return (True, verb)
    new_id = data.get("id")
    return (True, f"{verb} id={new_id}" if new_id is not None else verb)


def delete_ruleset_by_name(slug: str, name: str) -> tuple[bool, str]:
    """Delete the ruleset named `name` if present. Returns (success, msg).

    `success` is True when the ruleset was deleted OR was already absent
    (both are the desired post-state). Used to remove the orphaned
    legacy `janitor-baseline` ruleset after the ratified pair lands.
    """
    if not gh_available():
        return (False, "gh CLI not in PATH")
    rid = ruleset_id_by_name(slug, name)
    if rid is None:
        return (True, "absent")
    try:
        proc = subprocess.run(
            [
                "gh", "api", "--method", "DELETE",
                f"repos/{slug}/rulesets/{rid}",
            ],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return (False, f"gh subprocess failed: {exc}")
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().splitlines()[-1:] or ["gh exited non-zero"]
        return (False, err[0])
    return (True, f"deleted id={rid}")


def apply_baseline_rulesets(
    slug: str, default_branch: str, project_root: Path,
) -> tuple[bool, list[tuple[str, bool, str]], list[dict]]:
    """Apply BOTH ratified rulesets idempotent-by-name, then delete the
    legacy `janitor-baseline` orphan.

    `project_root` is the directory whose `.github/workflows/` is parsed
    to auto-detect the required CI check contexts (see
    `detect_required_status_checks` — workflow-config, not runtime
    check-runs, so a fresh repo's first PR is still gated and we never
    feed wrong contexts that 422 the rulesets API).

    Returns (all_ok, results, checks) where:
      * `results` is a list of (label, ok, message) tuples — one per
        applied ruleset plus one for the legacy cleanup,
      * `all_ok` is True iff every step succeeded,
      * `checks` is the auto-detected required-status-checks list that
        was actually embedded in the applied payloads. The caller reuses
        this for its announcement so the displayed checks match the
        applied ones exactly (and so detection runs ONCE, not once here +
        once in the caller).

    The ruleset list is fetched ONCE up front: if that lookup fails we
    can't safely tell PATCH from POST (and would risk a duplicate), so
    we abort the whole apply with a single failure result.
    """
    rulesets = list_existing_rulesets(slug)
    if rulesets is None:
        return (False, [("list", False, "ruleset list lookup failed")], [])
    by_name: dict[str, int] = {}
    for r in rulesets:
        if isinstance(r, dict):
            rid = r.get("id")
            nm = r.get("name")
            if isinstance(rid, int) and isinstance(nm, str):
                by_name[nm] = rid

    checks = detect_required_status_checks(project_root)
    payloads = baseline_ruleset_payloads(default_branch, checks)

    results: list[tuple[str, bool, str]] = []
    rulesets_ok = True
    for payload in payloads:
        name = payload["name"]
        ok, msg = _post_or_patch_ruleset(slug, payload, by_name.get(name))
        results.append((name, ok, msg))
        if not ok:
            rulesets_ok = False

    # Only remove the pre-ratification orphans once BOTH ratified rulesets are
    # confirmed in place — otherwise a failed apply would strip the legacy
    # protection and leave the branch unprotected. The baseline-* pair is created
    # FIRST (above), so there is no unprotected window during the rename. Deletes
    # the SHARED UNION (janitor + maintainer lineage) by exact name so a repo
    # either plugin ever touched fully converges. Idempotent — a missing legacy
    # ruleset reports success "absent".
    all_ok = rulesets_ok
    if rulesets_ok:
        for legacy_name in LEGACY_RULESET_NAMES:
            legacy_ok, legacy_msg = delete_ruleset_by_name(slug, legacy_name)
            results.append((legacy_name, legacy_ok, legacy_msg))
            if not legacy_ok:
                all_ok = False
    else:
        for legacy_name in LEGACY_RULESET_NAMES:
            results.append((legacy_name, True, "kept (ratified apply incomplete)"))

    return (all_ok, results, checks)


def guard_mode_enabled() -> bool:
    """Master gate for the Tier 2 auto path. Default is False — the
    user must explicitly enable per-project."""
    val = os.environ.get("CLAUDE_PLUGIN_OPTION_GUARD_MODE_ENABLED", "")
    return val.strip().lower() in ("1", "true", "yes", "on")
