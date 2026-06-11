---
name: janitor-branch-protection-setup
description: Applies the ratified two-ruleset branch-protection baseline on the default branch of the project's GitHub repo — baseline-history-protect (block force-push/deletion + linear history) and baseline-pr-and-checks (PR with 1 approval + dismiss-stale + thread-resolution + auto-detected required status checks). Idempotent — re-running PATCHes in place and never duplicates; an orphaned legacy janitor-baseline ruleset is cleaned up. Trigger with /janitor-branch-protection-setup, "set up branch protection", "harden the default branch", or "add a baseline ruleset to GitHub".
---

# Janitor branch-protection setup

## Overview

Applies the **ratified two-ruleset baseline** (janitor #14 /
maintainer #7) on the GitHub default branch. Both rulesets target the
`~DEFAULT_BRANCH` magic ref (so the JSON is portable across
main/master/custom defaults and byte-identical with the maintainer
plugin), `target: branch`, `enforcement: active`:

1. **`baseline-history-protect`** — `bypass_actors: []`
   * `deletion` — blocks branch deletion
   * `non_fast_forward` — blocks force-pushes
   * `required_linear_history` — fast-forward / squash only (no merge
     commits)
2. **`baseline-pr-and-checks`** — `bypass_actors: [{actor_id: 5,
   actor_type: RepositoryRole, bypass_mode: always}]` (the repo-admin
   role gets an always-bypass so a solo admin is not locked out of their
   own repo by the self-approval requirement)
   * `pull_request` with `required_approving_review_count: 1`,
     `dismiss_stale_reviews_on_push: true`,
     `require_code_owner_review: false`,
     `require_last_push_approval: false`,
     `required_review_thread_resolution: true`
   * `required_status_checks` with
     `strict_required_status_checks_policy: true` and a
     `required_status_checks` list of `{context: <job>}` entries that is
     **auto-detected** from the repo's live CI check-runs at apply time
     (empty list when CI has not run yet — never hard-coded)

This is the same baseline the Tier 2 guarded auto path
(`scripts/guard/branch_protection_apply.py`) applies — single source of
truth in `scripts/lib/branch_protection_lib.py::baseline_ruleset_payloads()`.
The Tier 1 surface (this skill) is for users who want a one-shot
interactive setup; Tier 2 is for users who flip `guard_mode_enabled` on
and forget.

Both surfaces are idempotent-by-name: each ratified ruleset is PATCHed if
one with the same name already exists, else POSTed — so re-running this
skill is safe and produces no double-apply. After both land, any orphaned
pre-migration `janitor-baseline` ruleset is **deleted** (only once both
ratified rulesets are confirmed in place — a failed apply never strips
the legacy protection).

See [references/ratified-baseline.md](references/ratified-baseline.md)
for the full payloads, the auto-detection query, and the apply algorithm.
Its table of contents:

* The three rulesets
* Why `~DEFAULT_BRANCH`
* Why the admin bypass on baseline-pr-and-checks
* Why tag protection (baseline-tag-protect)
* Required status checks — auto-detection
* Apply algorithm (idempotent-by-name + legacy cleanup)
* Single source of truth

## Prerequisites

* `gh` CLI installed and authenticated against the GitHub host that
  owns the repo.
* The authenticated viewer has **admin** permission on the repo (the
  ruleset endpoint requires it). The skill checks before posting.
* `.claude-plugin/plugin.json` declares `"repository"` as a
  `https://github.com/owner/repo` URL.
* `CLAUDE_PLUGIN_ROOT` env var is set (Claude Code sets it
  automatically for every plugin-shipped skill invocation; only
  matters if you call the helpers manually outside the slash command).

## Instructions

1. Resolve the repo slug from this project's `.claude-plugin/plugin.json`
   `repository` field (the helper lives in the plugin's installed
   source tree at `${CLAUDE_PLUGIN_ROOT}/scripts/lib/`, never the
   target project's source tree):

   ```bash
   uv run --python 3.12 -c "
   import sys, os
   sys.path.insert(0, os.environ['CLAUDE_PLUGIN_ROOT'] + '/scripts/lib')
   import branch_protection_lib as bpl
   from pathlib import Path
   print(bpl.detect_repo_slug(Path.cwd()) or '')
   "
   ```

2. Show the user the EXACT payloads the next step will apply, with the
   auto-detected required status checks already resolved (Tier 1's
   defining property: judgment + review):

   ```bash
   uv run --python 3.12 --with pyyaml -c "
   import json, sys, os
   from pathlib import Path
   sys.path.insert(0, os.environ['CLAUDE_PLUGIN_ROOT'] + '/scripts/lib')
   import branch_protection_lib as bpl
   slug = '<slug>'
   default_branch = bpl.detect_default_branch(slug) or '<default>'
   # Contexts come from THIS repo's .github/workflows/* (config, not
   # runtime check-runs — so the first PR is gated and no 422). The repo
   # being protected is the current project dir.
   project_root = Path(os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd())
   checks = bpl.detect_required_status_checks(project_root)
   print('auto-detected required checks:', [c['context'] for c in checks] or '(none — no workflow jobs found)')
   for p in bpl.baseline_ruleset_payloads(default_branch, checks):
       print(json.dumps(p, indent=2))
   "
   ```

   Render BOTH JSON payloads (and the auto-detected check list) to the
   user verbatim and ask "apply this?" before running step 3. This is
   the explicit human-in-the-loop step that keeps Tier 1 RULE-1
   compliant.

3. On user confirmation, apply both rulesets (idempotent-by-name) and
   clean up the legacy orphan:

   ```bash
   uv run --python 3.12 --with pyyaml -c "
   import sys, os
   from pathlib import Path
   sys.path.insert(0, os.environ['CLAUDE_PLUGIN_ROOT'] + '/scripts/lib')
   import branch_protection_lib as bpl
   slug = '<slug>'
   default_branch = bpl.detect_default_branch(slug)
   project_root = Path(os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd())
   if not bpl.gh_available():
       print('ERR gh not in PATH'); sys.exit(1)
   if not bpl.viewer_is_admin(slug):
       print(f'ERR viewer is not admin on {slug}'); sys.exit(1)
   present = bpl.baselines_present(slug)
   if present is None:
       print('ERR ruleset list lookup failed'); sys.exit(1)
   if present:
       print('NOOP both ratified rulesets already present'); sys.exit(0)
   all_ok, results, checks = bpl.apply_baseline_rulesets(slug, default_branch, project_root)
   for name, ok, msg in results:
       print(('OK' if ok else 'FAIL'), name, msg)
   sys.exit(0 if all_ok else 1)
   "
   ```

   `apply_baseline_rulesets` PATCHes each ratified ruleset that already
   exists (by name) and POSTs the rest, then DELETEs the orphaned
   `janitor-baseline` ruleset — but only once both ratified rulesets are
   confirmed in place.

4. Report one line per ruleset — `OK`/`FAIL <reason>` — or `NOOP` if
   both were already present, and stop. Do NOT chain into other actions;
   if the user wants the auto path on, they'll flip `guard_mode_enabled`
   separately.

## Output

One line per ratified ruleset (plus the legacy cleanup). On success:
`Branch-protection baseline applied to <slug>@<branch>: baseline-history-protect (created/updated), baseline-pr-and-checks (created/updated), janitor-baseline (deleted/absent).`
On noop: `Branch-protection baseline already present on <slug>@<branch>.`
On failure: `Branch-protection baseline NOT fully applied: <ruleset>: <reason>.`

## Error Handling

* `gh` missing → abort with `gh CLI not installed`.
* Viewer not admin → abort with `viewer is not admin on <slug>`.
* `gh api repos/<slug>` fails (network / 404) → abort with the trimmed
  stderr.
* Ruleset list lookup fails → abort BEFORE applying (can't tell PATCH
  from POST → would risk a duplicate).
* A ruleset POST/PATCH fails (422 schema mismatch, 403 token scope, …) →
  report the trimmed `gh` stderr; the other ratified ruleset is applied
  independently, but the legacy `janitor-baseline` orphan is KEPT (a
  failed apply must never strip the existing protection).

## Examples

```text
User: /janitor-branch-protection-setup
User: set up branch protection on this repo
User: harden the default branch
User: add a baseline ruleset to GitHub
```

## Scope

This skill ONLY applies the ratified two-ruleset baseline (and removes
the legacy `janitor-baseline` orphan). It does NOT enable the Tier 2
auto path (`guard_mode_enabled`), does NOT change CODEOWNERS, does NOT
touch workflow YAMLs, does NOT modify the .github/ directory in any way.
The Tier 2 path is a separate opt-in via plugin.json.

## Resources

* `scripts/lib/branch_protection_lib.py` —
  `baseline_ruleset_payloads()` (the two ratified payloads),
  `detect_required_status_checks()` (CI auto-detection),
  `apply_baseline_rulesets()` (idempotent POST/PATCH + legacy cleanup),
  and every `gh` call used by both Tier 1 (this skill) and Tier 2
  (`scripts/guard/branch_protection_apply.py`).
* `scripts/guard/branch_protection_apply.py` — the Tier 2 auto path
  (runs only when `guard_mode_enabled` is true).
* [references/ratified-baseline.md](references/ratified-baseline.md) —
  the full payloads, the auto-detection query + exact API shape, and the
  apply/cleanup algorithm. Its table of contents:
  * The three rulesets
  * Why `~DEFAULT_BRANCH`
  * Why the admin bypass on baseline-pr-and-checks
  * Why tag protection (baseline-tag-protect)
  * Required status checks — auto-detection
  * Apply algorithm (idempotent-by-name + legacy cleanup)
  * Single source of truth
* TRDD-631fa3de §10 — the Option B design this implements; the ratified
  unified baseline (janitor #14 / maintainer #7).

## Checklist

Copy this checklist and track your progress:

* [ ] Resolve `slug` from `.claude-plugin/plugin.json` (or ask user to
      paste it if the manifest is missing)
* [ ] Resolve the default branch via `gh api repos/<slug>` `.default_branch`
* [ ] Auto-detect required checks (`detect_required_status_checks(project_root)`
      — parses `.github/workflows/*`)
* [ ] Render BOTH baseline payload JSONs (with the resolved checks) for
      user review
* [ ] Confirm the user wants to apply (DO NOT skip this step — Tier 1
      is human-in-the-loop by definition)
* [ ] Check viewer is admin (`gh api repos/<slug>` `.permissions.admin`)
* [ ] Convergence check (`baselines_present(slug)`) — bail with NOOP if
      BOTH ratified rulesets are already in place
* [ ] Apply via `bpl.apply_baseline_rulesets(slug, default_branch, project_root)`
      (PATCH-or-POST both + delete legacy orphan)
* [ ] Report one `OK`/`FAIL` line per ruleset (or `NOOP`)
