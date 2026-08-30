#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Tier 2 GUARDED AUTO-REMEDIATION — branch-protection baseline applier.

Per TRDD-631fa3de Option B (recommended + 1) + the ratified unified
baseline (janitor #14 / maintainer #7): the janitor takes ONE specific
autonomous action — applying the ratified PAIR of branch rulesets on the
default branch — WITHOUT a human in the loop. Every other "acting"
remains in user-invoked skills.

The path is deliberately separate from `scripts/detectors/` (which are
read-only by contract). Dispatch calls this module from a dedicated
phase (`_phase_guard_branch_protection`) on its own cadence
(`guard_branch_protection_interval`, default 6 h). Every safety gate
listed below lives inside this module so the dispatch wiring stays
trivial — no coordination with the read-only branch-protection detector
is needed; the apply is idempotent-by-name (PUT if the ruleset already
exists, else POST — PUT, never PATCH: GitHub's "update a ruleset"
endpoint is PUT and a PATCH 404s on the live API, janitor#14) so
re-running converges instead of duplicating.

The ratified baseline is THREE rulesets (single source of truth in
`branch_protection_lib.baseline_ruleset_payloads` — build payloads
from that code, never from this prose, which has drifted before: it
said "TWO" and "PATCH" and "1 approval" until 2026-08-27, all three
stale):
  * `baseline-history-protect` — deletion only (NO non_fast_forward —
    USER Tier-3 ruling 2026-08-27 requires history rewrite/force-push
    to be allowed in every ruleset on every repo; NO required_linear_history
    — it jams the many-agent merge workflow); repo-admin role gets an
    `always` bypass.
  * `baseline-pr-and-checks` — pull_request (0 approvals — GitHub
    forbids self-approval, so any non-zero count is unsatisfiable on a
    solo-owner repo; dismiss-stale, thread-resolution) +
    required_status_checks (strict; CI contexts auto-detected at apply
    time); repo-admin role gets an `always` bypass so a solo admin is
    not locked out.
  * `baseline-tag-protect` — deletion + update on every tag (release
    tags are immutable to non-admins); repo-admin role gets an `always`
    bypass (USER ruling 2026-08-27 — with no bypass, a permitted history
    rewrite stranded every existing tag on a commit that no longer
    existed, with no way to move it). New-tag CREATION stays open, so
    `publish.py` still cuts releases.
After applying all three, any orphaned pre-migration `janitor-baseline`
ruleset is deleted.

Safety gates (any one false → no action, surface verbatim instead):
  * `guard_mode_enabled` env-var is truthy
  * `state.autofix_enabled()` is true (the per-project toggle from
    `/janitor-autofix-off` also vetoes guarded actions — one fewer
    switch for users to remember)
  * the repo slug is resolvable from `<plugin-root>/.claude-plugin/plugin.json`
  * `gh` CLI is on PATH
  * the repo's default branch is discoverable via `gh api`
  * the authenticated viewer is admin on the repo
  * the ruleset list is fetchable (else uncertain → don't act)

On success:
  * appends to `.janitor/logs/branch-protection-apply.log` with the
    timestamp, repo, per-ruleset result, and the exact payloads (audit
    trail).
  * appends a ledger line to `.janitor/state/branch-protection-acted.txt`
    so the human can see what was applied (also detected by
    `baselines_present()`, but the ledger is cheap to inspect by hand).
  * prints ONE loud announcement line to stdout — the heartbeat
    surfaces it to the user with full context.

Failure modes (each surfaces a single line, never half-applies a given
ruleset):
  * gh missing / network failure / non-admin viewer / 403 / 422 →
    one drift line explaining what blocked the action.

Exit codes:
  0 — completed cleanly (acted OR a precondition correctly vetoed).
  1 — unrecoverable error (e.g. cannot write the audit log).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "lib"))

import branch_protection_lib as bpl  # noqa: E402
import state  # noqa: E402

_LEDGER_FILE = "branch-protection-acted.txt"


def _project_has_github_remote(root: Path) -> bool:
    """True when `root` is a git repo whose origin points at github.com.

    The discriminator between "this project is not a GitHub repo" (routine, silent) and "this
    project IS on GitHub and the applier still cannot name it" (unexpected, worth a finding).
    Deliberately cruder than `detect_repo_slug`'s parser: it asks only whether github.com is in
    the origin URL at all, because the interesting case is exactly a URL that git accepts and
    that parser rejects. Matching the parser here would make the two agree by construction and
    the finding could never fire.
    """
    proc = state.run_subprocess(
        ["git", "-C", str(root), "remote", "get-url", "origin"],
        timeout=10,
        detector_name="branch-protection-apply",
    )
    return bool(proc and proc.returncode == 0 and "github.com" in (proc.stdout or ""))
_LOG_FILE = "branch-protection-apply.log"


def _audit_append(line: str) -> None:
    log_path = state.log_dir() / _LOG_FILE
    log_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"{ts}\t{line}\n")


def _ledger_append(slug: str, default_branch: str, msg: str) -> None:
    ledger = state.state_dir() / _LEDGER_FILE
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
    with ledger.open("a", encoding="utf-8") as f:
        f.write(f"{ts}\t{slug}\t{default_branch}\t{msg}\n")


def main() -> int:
    state.init_state()

    # Gate 1: master switch.
    if not bpl.guard_mode_enabled():
        return 0  # silent — the user has not opted in

    # Gate 2: project-scope autofix toggle. /janitor-autofix-off vetoes
    # guarded actions too — one fewer switch for the user to remember.
    if not state.autofix_enabled():
        state.log_line(
            "branch-protection-apply",
            "skip: /janitor-autofix-off is set — guard mode honours the project toggle",
        )
        return 0

    # Gate 3: resolve repo slug from this project's plugin.json (if any).
    plugin_root_env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if not plugin_root_env:
        # Fall back to project root when CLAUDE_PLUGIN_ROOT is unset
        # (e.g. dispatch.py was invoked outside a plugin context).
        plugin_root_env = os.environ.get("CLAUDE_PROJECT_DIR", "")
    plugin_root = Path(plugin_root_env or ".")
    slug = bpl.detect_repo_slug(plugin_root)
    if not slug:
        state.log_line(
            "branch-protection-apply",
            "skip: cannot resolve owner/repo slug from plugin.json or the git remote",
        )
        # RAISE, don't just log — but ONLY when a GitHub remote exists (TRDD-H8WRCW0I).
        #
        # A silent decline here is the defect: the DETECTOR half resolves the repo by its own
        # route (`gh repo view`) and keeps filing accurate findings, while this half cannot name
        # the repo and applies nothing, forever. One log line in a file nobody reads was the only
        # dissent, and every user-facing surface — heartbeat, fresh `last-run` stamp, other
        # detectors' findings — reported health. Measured on a peer's host: four declines a day
        # for days while its detector filed real issues about the very repo it could not name.
        #
        # THE GUARD ON THE GUARD: `_project_has_github_remote` is what keeps this from becoming
        # noise. Most projects the janitor runs in are not GitHub repos at all, and a finding per
        # pass on each of those would train its reader to ignore the channel — the card's own
        # "do NOT make gate 3 loud without fixing resolution" warning. Resolution is fixed now
        # (the remote fallback), so reaching here WITH a GitHub remote means something genuinely
        # unexpected: a URL git accepts that this cannot parse. That is worth a human's attention;
        # having no remote is not.
        if _project_has_github_remote(plugin_root):
            try:
                import issue_catalog  # noqa: PLC0415 - lazy: a missing lib must not kill the guard

                issue_catalog.raise_issue(
                    "BRPROT-003", where=str(plugin_root), slug=str(plugin_root),
                )
            except Exception:  # noqa: BLE001 - reporting must never break the caller
                pass
        return 0

    # Gate 4: gh availability.
    if not bpl.gh_available():
        print(
            "[branch-protection] guard mode ON but `gh` CLI not in PATH — "
            "install GitHub CLI to apply the baseline ruleset.",
        )
        return 0

    # Gate 5: default branch discovery.
    default_branch = bpl.detect_default_branch(slug)
    if not default_branch:
        state.log_line(
            "branch-protection-apply",
            f"skip: could not resolve default branch of {slug}",
        )
        return 0

    # Gate 6: convergence short-circuit — by NAME **and CONTENT** (TRDD-DD0M4QL7).
    # Name-presence alone let a hand-loosened or older-parameter ruleset stay
    # "converged" forever: the baseline could be created but never MAINTAINED
    # (the fleet's 8-of-9 staleness). Content drift falls THROUGH to the apply —
    # restoring drifted rules to the ratified baseline is the explicitly EXEMPT
    # idempotent re-apply (manager-approval-defaults §F). None anywhere means a
    # lookup failed → uncertain → don't act.
    present = bpl.baselines_present(slug)
    if present is None:
        state.log_line(
            "branch-protection-apply",
            f"skip: ruleset list lookup failed for {slug}",
        )
        return 0
    if present:
        verdict = bpl.baselines_content_current(slug, default_branch, plugin_root)
        if verdict is None:
            state.log_line(
                "branch-protection-apply",
                f"skip: ruleset detail lookup failed for {slug} — content unverified",
            )
            return 0
        current, reasons = verdict
        if current:
            # The converged no-op leaves ONE honest trace per pass, so silence
            # stops being ambiguous between "checked and converged" and
            # "never checked" (the card's silent-short-circuit finding).
            state.log_line(
                "branch-protection-apply",
                f"converged: all 3 baseline rulesets present and content-current on {slug}",
            )
            ledger = state.state_dir() / _LEDGER_FILE
            if not ledger.is_file():
                _ledger_append(slug, default_branch, "already-present")
            return 0
        state.log_line(
            "branch-protection-apply",
            f"content drift on {slug}: " + "; ".join(reasons[:4])
            + (f" (+{len(reasons) - 4} more)" if len(reasons) > 4 else ""),
        )
        # fall through: gate 7 + the ratified re-apply repair the drift

    # Gate 7: admin permission (can't configure what we can't administer).
    if not bpl.viewer_is_admin(slug):
        print(
            f"[branch-protection] guard mode ON for {slug}@{default_branch} but the "
            "authenticated viewer is not an admin — surface for human review.",
        )
        return 0

    # All gates passed → apply BOTH rulesets idempotent-by-name, then
    # delete the legacy orphan. apply_baseline_rulesets auto-detects the
    # CI check contexts by PARSING this project's `.github/workflows/*`
    # (so required_status_checks gates on the repo's configured jobs even
    # before CI first runs) and returns the exact list it applied, which
    # we reuse for the announcement (one detection pass, no display/apply
    # skew). `plugin_root` is this project's root (resolved above).
    all_ok, results, checks = bpl.apply_baseline_rulesets(
        slug, default_branch, plugin_root,
    )
    if not all_ok:
        # Surface the first failing step; the rest are in the audit log.
        first_fail = next((r for r in results if not r[1]), None)
        detail = (
            f"{first_fail[0]}: {first_fail[2]}" if first_fail else "unknown error"
        )
        print(
            f"[branch-protection] guard-mode baseline apply FAILED for "
            f"{slug}@{default_branch}: {detail}",
        )
        for name, ok, msg in results:
            _audit_append(
                f"{'OK' if ok else 'FAIL'}\t{slug}\t{default_branch}\t{name}\t{msg}",
            )
        return 0

    # Loud + auditable announcement. Record both emitted payloads.
    # Same slug-aware decision the applier used, so the AUDIT RECORD shows the payloads that
    # were actually applied. Recomputing it without the slug would log a PR rule this repo
    # never received (or omit one it did) — an audit trail that disagrees with reality.
    payloads = bpl.baseline_ruleset_payloads(
        default_branch, checks, require_pull_request=bpl.require_pull_request_for(slug)
    )
    payloads_json = json.dumps(payloads, separators=(",", ":"))
    summary = "; ".join(f"{name}={msg}" for name, _ok, msg in results)
    _audit_append(f"OK\t{slug}\t{default_branch}\t{summary}\t{payloads_json}")
    _ledger_append(slug, default_branch, f"applied ({summary})")
    check_note = (
        f"{len(checks)} required check(s): "
        + ", ".join(c["context"] for c in checks)
        if checks
        else "no required checks auto-detected (CI has not run yet)"
    )
    # DERIVED from the payload that was actually emitted, never restated by hand. This line is
    # the human-facing record of what was applied (see the module docstring), and a hand-written
    # copy of a payload drifts the moment the payload changes: it read "pull_request 1-approval"
    # long after the ratified count became 0 (USER Tier-3 ruling 2026-08-13 — GitHub forbids
    # self-approval, so 1 was unsatisfiable on a solo-owner repo), and it claimed the rule
    # unconditionally even though `require_pull_request_for` omits it on most repos. An operator
    # reading the audit log would have believed a review gate that is not there.
    pr_rules = {
        r["type"]: r.get("parameters", {})
        for p in payloads
        if p["name"] == bpl.PR_CHECKS_RULESET_NAME
        for r in p["rules"]
    }
    if "pull_request" in pr_rules:
        approvals = pr_rules["pull_request"].get("required_approving_review_count", 0)
        pr_note = f"pull_request {approvals}-approval/dismiss-stale/thread-resolution"
    else:
        pr_note = "no pull_request rule (single-party repo — see require_pull_request_for)"
    checks_note = (
        "required_status_checks strict" if "required_status_checks" in pr_rules
        else "no required_status_checks rule"
    )
    print(
        f"[guard] applied branch-protection baseline on {slug}@{default_branch} "
        f"({summary}). Rulesets: baseline-history-protect (deletion only — "
        f"history rewrite/force-push allowed), baseline-pr-and-checks "
        f"({pr_note} + {checks_note}), and baseline-tag-protect "
        f"(tag refs/tags/v*.*.* deletion + update, owner bypass); {check_note}. "
        f"Audit log: .janitor/logs/{_LOG_FILE}. Ledger: .janitor/state/{_LEDGER_FILE}.",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
