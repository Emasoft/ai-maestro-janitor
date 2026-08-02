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
`.github/workflows/` under the project root it is handed. For the repo whose checkout IS the
cwd that root is the cwd; for a remote fleet repo the workflow files are FETCHED via
`gh api repos/<slug>/contents/...` and staged into a temp `.github/workflows/` first, so the
SAME parser (`detect_required_status_checks`) reads them — one implementation, no divergence
between local and fleet behavior. This closed the last 157OH2D7 gap: the 13th fleet repo kept
its NO_REQUIRED_CHECKS finding forever because the fix could only discover contexts for the
cwd repo. When the fetch yields nothing (no workflows, no net, no auth) the
`required_status_checks` RULE IS OMITTED — GitHub 422s an empty contexts array and that 422
fails the whole ruleset write, so emitting it would take the `pull_request` gate down with it
(observed live: 11 of 12 fleet repos 422'd while the one repo that WAS the cwd succeeded).
The PR-review gate still lands regardless; the merge-jam + unprotected fixes do NOT depend on
any of that.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import subprocess
import sys
import tempfile
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


# Bounds on the remote-workflow fetch — a repo with hundreds of workflow files (or one
# gigantic one) must not turn a config fix into a download job. Generous vs reality: the
# fleet's busiest repo has 3.
_MAX_REMOTE_WORKFLOWS = 25
_MAX_WORKFLOW_BYTES = 512 * 1024

# Keep every staged temp tree alive until interpreter exit: apply_baseline_rulesets reads
# the staged files AFTER _project_root_for returns, so an eagerly-cleaned TemporaryDirectory
# would hand it an empty root and silently regress to the no-contexts behavior.
_STAGED_TMPDIRS: list[tempfile.TemporaryDirectory] = []


def _fetch_remote_workflows(slug: str) -> dict[str, str]:
    """`{filename: content}` for `slug`'s `.github/workflows/*.yml|yaml`, via `gh api`.

    Never raises — every failure (no dir, no auth, no net, bad base64) degrades to an
    empty dict, which downstream means "no contexts detected", exactly the pre-fetch
    behavior. The listing and each file body come from the contents API; the body is the
    JSON `content` field (base64), decoded here rather than shelled through `base64` so a
    single malformed file skips cleanly."""
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["gh", "api", f"repos/{slug}/contents/.github/workflows"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        if proc.returncode != 0:
            return {}
        listing = json.loads(proc.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return {}
    if not isinstance(listing, list):
        return {}
    out: dict[str, str] = {}
    for entry in listing[:_MAX_REMOTE_WORKFLOWS]:
        name = entry.get("name") if isinstance(entry, dict) else None
        if not isinstance(name, str) or not name.endswith((".yml", ".yaml")) or "/" in name:
            continue
        if entry.get("size") and entry["size"] > _MAX_WORKFLOW_BYTES:
            continue
        try:
            body = subprocess.run(  # noqa: S603 - fixed argv, no shell
                ["gh", "api", f"repos/{slug}/contents/.github/workflows/{name}", "--jq", ".content"],
                capture_output=True, text=True, timeout=30, check=False,
            )
            if body.returncode != 0:
                continue
            out[name] = base64.b64decode(body.stdout).decode("utf-8")
        except (OSError, subprocess.SubprocessError, binascii.Error, UnicodeDecodeError):
            continue
    return out


def _stages_conservatively(content: str) -> bool:
    """May this REMOTE workflow feed `detect_required_status_checks`? (2026-08-02 review
    finding.) The shared parser derives a context per job as `name or job_id`, which is
    blind to two shapes that make a REQUIRED context never report — wedging every
    non-admin PR in 'Expected — waiting for status', unmergeable:

    - ``strategy.matrix``: the real checks report as 'name (3.11)' etc.; the bare name
      never reports.
    - ``paths:`` / ``paths-ignore:`` on the PR trigger: on non-matching PRs the workflow
      never runs at all.

    For the LOCAL checkout the operator can see and fix a wedge; for the 12 FLEET repos
    this tool writes to unattended, omission (a less-strict ruleset) is strictly safer
    than a never-reporting required check — so such files are not staged. The shared
    parser itself is untouched: its output must stay byte-identical with the maintainer
    plugin's (janitor#14). Unparseable ⇒ False (the parser would skip it anyway)."""
    import yaml  # lazy — mirrors branch_protection_lib's own lazy import

    try:
        wf = yaml.safe_load(content)
    except yaml.YAMLError:
        return False
    if not isinstance(wf, dict):
        return False
    # YAML parses a bare `on:` key as boolean True — accept both spellings.
    triggers = wf.get("on", wf.get(True, {}))
    if isinstance(triggers, dict):
        for trig in ("pull_request", "pull_request_target"):
            cfg = triggers.get(trig)
            if isinstance(cfg, dict) and ("paths" in cfg or "paths-ignore" in cfg):
                return False
    jobs = wf.get("jobs", {})
    if isinstance(jobs, dict):
        for job_cfg in jobs.values():
            if isinstance(job_cfg, dict) and isinstance(job_cfg.get("strategy"), dict) \
                    and "matrix" in job_cfg["strategy"]:
                return False
    return True


def _project_root_for(slug: str, current_slug: str | None) -> Path:
    """A root whose `.github/workflows/` holds `slug`'s workflow files: the cwd when `slug`
    IS the current checkout, else a temp stage filled from the remote repo — so
    `detect_required_status_checks` (the ONE parser) discovers contexts for fleet repos
    too, not just the local one. A failed/empty fetch returns a path with no workflows dir,
    which downstream reads as "no contexts" (the safe pre-fetch behavior). Remote files
    that could yield never-reporting contexts are NOT staged — see
    `_stages_conservatively`."""
    if current_slug and slug == current_slug:
        return Path.cwd()
    files = _fetch_remote_workflows(slug)
    if not files:
        return Path("/nonexistent-janitor-github-config-fix")
    tmp = tempfile.TemporaryDirectory(prefix="janitor-ghcfg-wf-")
    _STAGED_TMPDIRS.append(tmp)  # keep alive past this call — see the list's comment
    wf_dir = Path(tmp.name) / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    for name, content in files.items():
        if _stages_conservatively(content):
            (wf_dir / name).write_text(content, encoding="utf-8")
    return Path(tmp.name)


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
