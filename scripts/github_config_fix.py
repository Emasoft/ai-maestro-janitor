#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6.0"]
# ///
"""Backing script for /janitor-github-config-fix (TRDD-157OH2D7) — the on-demand FIX.

The heartbeat only NOTIFIES (the janitor cannot mutate a repo from a detector); this script
is the remedy the notification points at. It fixes the two problems the user reported plus the
CI/review baseline, across ONE repo or the whole ai-maestro fleet (`--all`):

  * `required_linear_history` (BLOCKS Claude's merges) — removed. When it lives in the
    janitor's own baseline-history-protect ruleset (the common case: an OLDER janitor version
    applied it), re-applying the CURRENT baseline PUTs the corrected rule set and drops it. When
    it lives in a USER-authored ruleset, we PUT that ruleset back with ONLY that rule removed —
    every other rule / condition / bypass actor preserved (strip_linear_history_payload).
  * UNPROTECTED / NO_PR_REVIEW / NO_REQUIRED_CHECKS / NO_TAG_PROTECT — the ratified baseline pair
    + tag protection, applied idempotent-by-name via branch_protection_lib.apply_baseline_rulesets
    (reuse; no new ruleset logic).

SAFETY (Tier-2 discipline):
  * PLAN-FIRST: run without --apply to print exactly what WOULD change and mutate NOTHING. The
    skill shows that plan and only runs --apply on the user's confirmation.
  * ADMIN-GATED: a repo where the authenticated viewer is not an admin is skipped (can't fix it).
  * Workflow/CI *content* findings (a vulnerable action, a secret leak) are NOT fixed here — the
    plan routes them to /janitor-github-workflow-doctor and /janitor-security-agent.

CI-context note: apply_baseline_rulesets auto-detects the required status-check contexts from
`.github/workflows/` of the LOCAL checkout. So the check contexts are detected only for a repo
whose working tree is the current directory; for a remote fleet repo we don't have locally, the
checks rule is still installed but gates on no specific contexts until you re-run this from that
repo's checkout. The merge-jam + unprotected fixes do NOT depend on that.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import branch_protection_lib as bpl  # noqa: E402
import github_config_audit as gca  # noqa: E402

# The finding codes this script can actually remedy by changing repo CONFIG (rulesets).
# NO_CI is deliberately NOT one of them: no ruleset change adds a CI workflow — that needs
# /janitor-github-workflow-create in the repo itself. Without this gate a repo whose ONLY
# finding is NO_CI still got the full 3-ruleset baseline PUT on --apply: a Tier-2 remote
# mutation for a gap this script cannot fix (and a plan line that promised otherwise).
_CONFIG_FIXABLE = frozenset(
    {"UNPROTECTED", "LINEAR_HISTORY", "NO_PR_REVIEW", "NO_REQUIRED_CHECKS", "NO_TAG_PROTECT"}
)


def _current_repo_slug() -> str | None:
    """The slug of the repo whose checkout is the cwd (so we can pass cwd as project_root and
    get CI contexts auto-detected for it)."""
    return bpl.detect_repo_slug(Path.cwd())


def _project_root_for(slug: str, current_slug: str | None) -> Path:
    """cwd when `slug` IS the current checkout (workflows are local → contexts detected), else
    a path with no `.github/workflows/` so detect_required_status_checks returns []."""
    if current_slug and slug == current_slug:
        return Path.cwd()
    return Path("/nonexistent-janitor-github-config-fix")


def _put_ruleset(slug: str, rid: int, payload: dict) -> tuple[bool, str]:
    """PUT (update) an existing ruleset by id with `payload`. Returns (ok, message).
    Used ONLY to strip required_linear_history from a non-baseline user ruleset."""
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["gh", "api", "--method", "PUT", f"repos/{slug}/rulesets/{rid}", "--input", "-"],
            input=json.dumps(payload), capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return (False, f"gh subprocess failed: {exc}")
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().splitlines()[-1:] or ["gh exited non-zero"]
        return (False, err[0])
    return (True, "updated")


def _plan_for_repo(facts: gca.RepoFacts) -> list[str]:
    """The ordered list of human-readable actions this fix would take on one repo (plan mode)."""
    actions: list[str] = []
    strips = gca.nonbaseline_rulesets_with_linear_history(facts.rulesets or [])
    for rs in strips:
        n_kept = len([r for r in (rs.get("rules") or []) if r.get("type") != "required_linear_history"])
        actions.append(
            f"PUT ruleset '{rs.get('name')}' dropping required_linear_history "
            f"(preserving its other {n_kept} rule(s), conditions, and bypass actors)"
        )
    actions.append(
        "apply the ratified baseline (baseline-history-protect [deletion + non_fast_forward, "
        "NO linear history], baseline-pr-and-checks [PR review + required checks], "
        "baseline-tag-protect) idempotent-by-name"
    )
    return actions


def _apply_for_repo(slug: str, facts: gca.RepoFacts, current_slug: str | None) -> list[str]:
    """Execute the fix on one repo. Returns per-step result lines."""
    out: list[str] = []
    # 1) Strip linear-history from any NON-baseline user ruleset (preserve the rest).
    for rs in gca.nonbaseline_rulesets_with_linear_history(facts.rulesets or []):
        rid = rs.get("id")
        name = rs.get("name")
        if not isinstance(rid, int):
            out.append(f"  ✗ '{name}': no numeric id, cannot PUT (skipped)")
            continue
        ok, msg = _put_ruleset(slug, rid, gca.strip_linear_history_payload(rs))
        out.append(f"  {'✓' if ok else '✗'} strip linear-history from '{name}': {msg}")
    # 2) Apply the ratified baseline (fixes UNPROTECTED / PR / checks / tag AND drops
    #    linear-history from the janitor's own baseline-history-protect by overwriting it).
    branch = facts.default_branch or bpl.detect_default_branch(slug) or ""
    if not branch:
        out.append("  ✗ could not resolve default branch — baseline NOT applied")
        return out
    all_ok, results, _checks = bpl.apply_baseline_rulesets(
        slug, branch, _project_root_for(slug, current_slug)
    )
    for label, ok, msg in results:
        out.append(f"  {'✓' if ok else '✗'} {label}: {msg}")
    out.append(f"  {'✓ all baseline steps ok' if all_ok else '✗ some baseline steps failed'}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Review + fix ai-maestro plugin repo GitHub config.")
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--slug", help="a single owner/repo to fix")
    grp.add_argument("--all", action="store_true", help="fix every ai-maestro plugin repo")
    ap.add_argument(
        "--apply", action="store_true",
        help="actually mutate the repo(s). WITHOUT this flag the script only PLANS (mutates nothing).",
    )
    ap.add_argument(
        "--plugins-root", default=str(Path.home() / ".claude" / "plugins"),
        help="plugins root holding the marketplace catalog (for --all)",
    )
    args = ap.parse_args()

    if args.slug:
        slugs = [args.slug]
    else:
        slugs = gca.fleet_repo_slugs(Path(args.plugins_root))
        if not slugs:
            print("No ai-maestro plugin repos found in the marketplace catalog.")
            return 0

    current = _current_repo_slug()
    mode = "APPLY" if args.apply else "PLAN (no changes made)"
    print(f"== /janitor-github-config-fix — {mode} — {len(slugs)} repo(s) ==")

    acted = 0
    for slug in slugs:
        facts = gca.gather_repo_facts(slug)
        if facts.admin is False:
            print(f"\n{slug}: SKIP — you are not an admin (cannot change its settings).")
            continue
        if facts.rulesets is None:
            print(f"\n{slug}: SKIP — could not read rulesets (indeterminate; try again).")
            continue
        findings = gca.classify_repo(facts)
        if not findings:
            print(f"\n{slug}: already compliant — nothing to fix.")
            continue
        codes = {f.code for f in findings}
        if not (codes & _CONFIG_FIXABLE):
            # Only non-config findings (today: NO_CI). Touching the rulesets would change
            # nothing about them, so do NOT mutate the repo — just route it.
            print(
                f"\n{slug}: {len(findings)} finding(s): " + ", ".join(sorted(codes))
                + " — SKIP: no ruleset change can fix this. Run /janitor-github-workflow-create"
                " in that repo to add CI."
            )
            continue
        acted += 1
        print(f"\n{slug}: {len(findings)} finding(s): " + ", ".join(f.code for f in findings))
        if args.apply:
            for line in _apply_for_repo(slug, facts, current):
                print(line)
            # Re-audit to prove the result.
            after = gca.classify_repo(gca.gather_repo_facts(slug))
            if after:
                print("  ⚠ remaining after fix: " + ", ".join(f.code for f in after)
                      + " (workflow/CI content findings route to /janitor-github-workflow-doctor"
                      " + /janitor-security-agent)")
            else:
                print("  ✓ all findings cleared.")
        else:
            for act in _plan_for_repo(facts):
                print(f"  - {act}")

    if not args.apply and acted:
        print(f"\nPlan only — nothing changed. Re-run with --apply to fix the {acted} repo(s) above.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
