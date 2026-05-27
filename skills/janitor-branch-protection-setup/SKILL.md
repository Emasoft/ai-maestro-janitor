---
name: janitor-branch-protection-setup
description: Sets up a baseline branch ruleset on the default branch of the project's GitHub repo — block force-pushes, block deletion, require linear history, require PR with 1 approval + dismiss-stale + thread-resolution. Tier 1 user-invoked skill from TRDD-631fa3de. Idempotent — re-running is a no-op when the ruleset is already in place. Trigger with /janitor-branch-protection-setup, "set up branch protection", "harden the default branch", or "add a baseline ruleset to GitHub".
---

# Janitor branch-protection setup

## Overview

Creates the janitor's **baseline** branch ruleset on the GitHub default
branch:

* `non_fast_forward` — blocks force-pushes
* `deletion`         — blocks branch deletion
* `required_linear_history` — fast-forward / squash only (no merge
  commits)
* `pull_request` with `required_approving_review_count: 1`,
  `dismiss_stale_reviews_on_push: true`,
  `required_review_thread_resolution: true`

This is the same baseline the Tier 2 guarded auto path
(`scripts/guard/branch_protection_apply.py`) applies — single source of
truth in `scripts/lib/branch_protection_lib.py`. The Tier 1 surface (this
skill) is for users who want a one-shot interactive setup; Tier 2 is for
users who flip `guard_mode_enabled` on and forget.

Both surfaces are idempotent: a ruleset named `janitor-baseline` is
recognised by exact name match, so re-running this skill is safe and
produces no double-apply.

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

2. Show the user the EXACT payload the next step will POST (Tier 1's
   defining property: judgment + review):

   ```bash
   uv run --python 3.12 -c "
   import json, sys, os
   sys.path.insert(0, os.environ['CLAUDE_PLUGIN_ROOT'] + '/scripts/lib')
   import branch_protection_lib as bpl
   default_branch = bpl.detect_default_branch('<slug>') or '<default>'
   print(json.dumps(bpl.baseline_ruleset_payload(default_branch), indent=2))
   "
   ```

   Render that JSON to the user verbatim and ask "apply this?" before
   running step 3. This is the explicit human-in-the-loop step that
   keeps Tier 1 RULE-1 compliant.

3. On user confirmation, POST the ruleset:

   ```bash
   uv run --python 3.12 -c "
   import sys, os
   sys.path.insert(0, os.environ['CLAUDE_PLUGIN_ROOT'] + '/scripts/lib')
   import branch_protection_lib as bpl
   slug = '<slug>'
   default_branch = bpl.detect_default_branch(slug)
   if not bpl.gh_available():
       print('ERR gh not in PATH'); sys.exit(1)
   if not bpl.viewer_is_admin(slug):
       print(f'ERR viewer is not admin on {slug}'); sys.exit(1)
   present = bpl.is_baseline_present(slug)
   if present is None:
       print('ERR ruleset list lookup failed'); sys.exit(1)
   if present:
       print('NOOP baseline already present'); sys.exit(0)
   ok, msg = bpl.create_baseline_ruleset(slug, default_branch)
   print('OK' if ok else 'FAIL', msg)
   "
   ```

4. Report one line — `OK`, `NOOP`, or `FAIL <reason>` — and stop. Do
   NOT chain into other actions; if the user wants the auto path on,
   they'll flip `guard_mode_enabled` separately.

## Output

One line. On success: `Branch-protection baseline applied to <slug>@<branch> (id=<n>).` On noop: `Branch-protection baseline already present on <slug>@<branch>.` On failure: `Branch-protection baseline NOT applied: <reason>.`

## Error Handling

* `gh` missing → abort with `gh CLI not installed`.
* Viewer not admin → abort with `viewer is not admin on <slug>`.
* `gh api repos/<slug>` fails (network / 404) → abort with the trimmed
  stderr.
* Ruleset list lookup fails → abort BEFORE posting (don't double-apply
  silently).
* POST fails (422 schema mismatch, 403 token scope, …) → report the
  trimmed `gh` stderr; no partial apply.

## Examples

```text
User: /janitor-branch-protection-setup
User: set up branch protection on this repo
User: harden the default branch
User: add a baseline ruleset to GitHub
```

## Scope

This skill ONLY creates the baseline ruleset. It does NOT enable the
Tier 2 auto path (`guard_mode_enabled`), does NOT change CODEOWNERS,
does NOT touch workflow YAMLs, does NOT modify the .github/ directory
in any way. The Tier 2 path is a separate opt-in via plugin.json.

## Resources

* `scripts/lib/branch_protection_lib.py` — payload definition + every
  `gh` call used by both Tier 1 (this skill) and Tier 2
  (`scripts/guard/branch_protection_apply.py`).
* `scripts/guard/branch_protection_apply.py` — the Tier 2 auto path
  (runs only when `guard_mode_enabled` is true).
* TRDD-631fa3de §10 — the Option B design this implements.

## Checklist

Copy this checklist and track your progress:

- [ ] Resolve `slug` from `.claude-plugin/plugin.json` (or ask user to
      paste it if the manifest is missing)
- [ ] Resolve the default branch via `gh api repos/<slug>` `.default_branch`
- [ ] Render the baseline payload JSON for user review
- [ ] Confirm the user wants to apply (DO NOT skip this step — Tier 1
      is human-in-the-loop by definition)
- [ ] Check viewer is admin (`gh api repos/<slug>` `.permissions.admin`)
- [ ] Idempotency check (`is_baseline_present(slug)`) — bail with NOOP
      if the baseline is already in place
- [ ] POST via `bpl.create_baseline_ruleset(slug, default_branch)`
- [ ] Report `OK`, `NOOP`, or `FAIL <reason>` in a single line
