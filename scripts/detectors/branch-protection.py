#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Branch-protection detector — flags an unprotected default branch.

A GitHub repo created without a branch ruleset / classic branch
protection lets anyone with write access force-push over history, delete
the default branch, or merge straight to it with no review — and GitHub
shows the persistent "Your main branch isn't protected" banner. For a
repo entrusted to the janitor, that state must never go unnoticed.

The detector asks the GitHub API (READ-ONLY) whether the default branch
is covered by EITHER:
  * a classic branch-protection rule
    (GET repos/{owner}/{repo}/branches/{branch}/protection → 200), or
  * at least one ACTIVE branch ruleset
    (GET repos/{owner}/{repo}/rulesets → any {target: "branch",
     enforcement: "active"}; the endpoint includes inherited org/enterprise
     rulesets by default, so org-level protection counts too).

If it can DEFINITIVELY confirm neither is present (rulesets list returned
cleanly with no active branch ruleset AND classic protection returned a
genuine 404) it surfaces ONE drift line with the remediation path. On any
non-definitive answer (transient error, 403, server error) it stays
silent — the janitor never nags about something it could not actually
verify, which is what keeps it free of false alarms.

It NEVER creates protection itself. Configuring a repo is a mutation the
user performs (or an explicitly-authorised guard mode, evaluated
separately) — a read-only heartbeat detector only surfaces.

Silent when: gh is absent, unauthenticated, the viewer is not a repo
admin (cannot fix it anyway), the repo has no GitHub remote, or any probe
fails.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import github_config_audit as gca  # noqa: E402
import issue_catalog  # noqa: E402
import security_helpers  # noqa: E402
import state  # noqa: E402

_NAME = "branch-protection"


def _gh_json(args: list[str], *, timeout: float = 15.0):
    """Run `gh <args>` read-only. Return (returncode, parsed_json_or_None).

    returncode is None when the subprocess itself could not run (gh missing
    or timed out — already logged by run_subprocess). stdout is always parsed
    when present, even on a non-zero exit, so the caller can inspect a 404
    error body's {"status": "404"} marker.
    """
    proc = state.run_subprocess(
        ["gh", *args],
        timeout=timeout,
        cwd=state.project_root(),
        detector_name=_NAME,
    )
    if proc is None:
        return None, None
    parsed = None
    if proc.stdout and proc.stdout.strip():
        try:
            parsed = json.loads(proc.stdout)
        except json.JSONDecodeError:
            parsed = None
    return proc.returncode, parsed


def main() -> int:
    if not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_BRANCH_PROTECTION_ENABLED", True):
        return 0
    # NOTE (TRDD-157OH2D7): unlike the pattern-scanning security detectors, this detector is
    # NOT self-scan-guarded. The self-scan guard exists so the janitor's own detection
    # SIGNATURES don't false-positive on its own source — but branch protection is a GitHub
    # API fact, not a source pattern, and the janitor's own repo must be held to the same
    # protection bar as any other plugin repo (it was found carrying required_linear_history).

    state.init_state()
    project_root = state.project_root()

    # Fast local short-circuit: not a git repo → no GitHub remote to check.
    git_dir = state.run_subprocess(
        ["git", "rev-parse", "--git-dir"], cwd=project_root, timeout=5, detector_name=_NAME
    )
    if git_dir is None or git_dir.returncode != 0:
        return 0

    # gh must be installed AND authenticated, else we cannot verify anything.
    auth = state.run_subprocess(["gh", "auth", "status"], timeout=10, detector_name=_NAME)
    if auth is None or auth.returncode != 0:
        state.log_line(_NAME, "gh not installed or not authenticated — skipping")
        return 0

    # Resolve owner/repo + default branch + the viewer's permission. Honor an
    # explicit repo-slug override (same knob the pr-reconciler uses) before
    # falling back to the origin remote that `gh repo view` infers.
    repo_slug = (os.environ.get("CLAUDE_PLUGIN_OPTION_GITHUB_REPO") or "").strip()
    view_args = ["repo", "view"]
    if repo_slug:
        view_args.append(repo_slug)
    view_args += ["--json", "nameWithOwner,defaultBranchRef,viewerPermission"]
    rc_v, info = _gh_json(view_args)
    if rc_v != 0 or not isinstance(info, dict):
        state.log_line(_NAME, "gh repo view failed (no GitHub remote?) — skipping")
        return 0

    owner_repo = info.get("nameWithOwner") or ""
    default_ref = info.get("defaultBranchRef")
    branch = (default_ref.get("name") if isinstance(default_ref, dict) else "") or ""
    viewer_perm = (info.get("viewerPermission") or "").upper()
    if not owner_repo or not branch:
        return 0

    # Only ADMIN can configure rulesets / branch protection. Nagging a
    # non-admin is pure noise — they cannot act on it. Empty/unknown perm
    # falls through to "surface" (better to over-surface a security gap than
    # silently swallow it when we genuinely could not classify the role).
    if viewer_perm not in ("ADMIN", ""):
        return 0

    # 1) classic branch protection: 200 = protected, genuine 404 = not.
    rc_p, prot = _gh_json(["api", f"repos/{owner_repo}/branches/{branch}/protection"])
    if rc_p is None:
        return 0
    classic_protected = rc_p == 0
    classic_is_404 = (
        rc_p != 0 and isinstance(prot, dict) and str(prot.get("status")) == "404"
    )

    # 2) active branch rulesets (includes inherited org/enterprise rulesets).
    rc_r, rulesets = _gh_json(["api", f"repos/{owner_repo}/rulesets"])
    if rc_r is None:
        return 0
    ruleset_probe_ok = rc_r == 0 and isinstance(rulesets, list)
    ruleset_protected = False
    if rc_r == 0 and isinstance(rulesets, list):
        for rs in rulesets:
            if (
                isinstance(rs, dict)
                and rs.get("target") == "branch"
                and rs.get("enforcement") == "active"
            ):
                ruleset_protected = True
                break

    where = f"{owner_repo}@{branch}"
    evidence = [f"github:{owner_repo}"]

    # The one-line remedy every finding here carries (TRDD-157OH2D7): the janitor can only
    # NOTIFY, so the notification MUST point at the fix. The proposal's approval command schedules
    # an agent; `/janitor-github-config-fix` is the fix the user can run RIGHT NOW (plan-first,
    # mutate-on-confirm). Both are offered because they answer different questions — "handle it for
    # me" and "show me exactly what you would change first".
    fix_hint = (
        f" → Or fix it now: {gca.FIX_SKILL} (plan-first; mutates only on your ok). "
        + security_helpers.security_agent_hint(
            "branch-protection",
            enabled=state.is_truthy_env(security_helpers.SECURITY_AGENT_HINT_ENV, True),
        )
    ).rstrip()

    # This is the USER's repo, so every finding here is PROJECT-domain: the janitor PROPOSES (it
    # authors a TRDD and hands back the exact approval command) and never touches the repo itself.
    # We print on `first_seen` only — the standing reminder is the scheduler's one job, and a
    # detector on a 6h cadence re-announcing an unapproved finding would just duplicate it. The
    # proposal is the dedupe now, so the old seen-file has nothing left to remember.

    # LINEAR-HISTORY (TRDD-157OH2D7): a `required_linear_history` rule BLOCKS merge commits and
    # jams the many-agent merge workflow — a distinct problem from being UNPROTECTED, and it
    # afflicts a PROTECTED repo (the janitor's own repo was found carrying it). Resolve it from
    # the rulesets we already listed (fetches per-ruleset detail only for the active branch
    # rulesets); emit ONLY on a definite True so an indeterminate probe never false-alarms.
    if ruleset_probe_ok:
        lin = gca.linear_history_present(
            owner_repo, rulesets if isinstance(rulesets, list) else []
        )
        if lin is True:
            r = issue_catalog.raise_issue(
                "BRPROT-002",
                where=where,
                evidence=evidence,
                slug=owner_repo,
                detail=f"a ruleset on '{branch}' requires LINEAR HISTORY, which blocks merge commits",
            )
            if r.first_seen and r.line:
                print(r.line + fix_hint)
            elif not r.ok:
                state.log_line(_NAME, f"could not raise BRPROT-002: {r.why}")
        elif lin is False:
            # The rule is gone — withdraw the proposal. A fixed finding must not be left on the
            # user's board as a problem that no longer exists.
            issue_catalog.clear_issue("BRPROT-002", where=where)

    if classic_protected or ruleset_protected:
        # Protected now. Withdraw any standing UNPROTECTED proposal so a future regression (the
        # ruleset being deleted / disabled) proposes afresh instead of finding a stale one and
        # staying mute.
        issue_catalog.clear_issue("BRPROT-001", where=where)
        state.rotate_log_if_big(_NAME)
        return 0

    # Only surface UNPROTECTED when BOTH negatives are DEFINITIVE. A transient/permission
    # error on either probe means we cannot prove the branch is unprotected, and an
    # unprovable claim is exactly the false alarm we refuse to emit.
    if not (ruleset_probe_ok and classic_is_404):
        state.log_line(_NAME, "protection status indeterminate — skipping")
        return 0

    r = issue_catalog.raise_issue("BRPROT-001", where=where, evidence=evidence, slug=owner_repo)
    if r.first_seen and r.line:
        print(r.line + fix_hint)
    elif not r.ok:
        state.log_line(_NAME, f"could not raise BRPROT-001: {r.why}")

    state.rotate_log_if_big(_NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
