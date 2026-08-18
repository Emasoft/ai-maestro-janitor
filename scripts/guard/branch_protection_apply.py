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
is needed; the apply is idempotent-by-name (PATCH if the ruleset already
exists, else POST) so re-running converges instead of duplicating.

The ratified baseline is TWO rulesets (single source of truth in
`branch_protection_lib.baseline_ruleset_payloads`):
  * `baseline-history-protect` — deletion + non_fast_forward (NO
    required_linear_history — it jams the many-agent merge workflow);
    no bypass actors.
  * `baseline-pr-and-checks` — pull_request (1 approval, dismiss-stale,
    thread-resolution) + required_status_checks (strict; CI contexts
    auto-detected at apply time); repo-admin role gets an `always`
    bypass so a solo admin is not locked out.
After applying both, any orphaned pre-migration `janitor-baseline`
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
            "skip: cannot resolve owner/repo slug from plugin.json",
        )
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
    print(
        f"[guard] applied branch-protection baseline on {slug}@{default_branch} "
        f"({summary}). Rulesets: baseline-history-protect (deletion + "
        f"non_fast_forward), baseline-pr-and-checks "
        f"(pull_request 1-approval/dismiss-stale/thread-resolution + "
        f"required_status_checks strict), and baseline-tag-protect "
        f"(tag refs/tags/v*.*.* deletion + update, no bypass); {check_note}. "
        f"Audit log: .janitor/logs/{_LOG_FILE}. Ledger: .janitor/state/{_LEDGER_FILE}.",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
