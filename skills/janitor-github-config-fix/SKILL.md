---
name: janitor-github-config-fix
description: Review and FIX GitHub-config drift on ai-maestro plugin repos found by the fleet github-config audit — a missing branch ruleset (UNPROTECTED default branch, open to stranger PRs/force-pushes), a required_linear_history rule that BLOCKS Claude's merges, or a missing PR-review / required-status-checks / tag-protection gate. Plan-first and mutate-only-on-confirmation: it prints exactly what would change, then applies only after you approve, and only on repos where you are an admin. Removes required_linear_history (preserving the rest of the ruleset) and applies the ratified baseline. Trigger with /janitor-github-config-fix, "fix the github config", "harden the plugin repos", "remove linear history so I can merge", or in response to a [github-config] heartbeat drift line.
---

# Janitor github-config-fix

## Overview

The fleet `github-config` heartbeat line tells you WHICH ai-maestro plugin repos have drifted
(UNPROTECTED default branch, `required_linear_history` blocking merges, missing CI/PR gate). The
janitor can only NOTIFY — it never mutates a repo from a detector. This skill is the remedy: it
reviews the named repo(s) and, on your confirmation, fixes them.

It is **plan-first** and **Tier-2 gated** — it prints exactly what it would change and mutates
nothing until you say go, and it skips any repo where you are not an admin (you couldn't change
its settings anyway).

## When to use

- A `[github-config]` heartbeat drift line appeared naming drifted plugin repos.
- You hit a merge that GitHub blocks with "required linear history" / "merge commits are not
  allowed" on a plugin repo.
- You want to harden a newly-created plugin repo to the ratified baseline.

## What it fixes

| Finding | Fix |
|---|---|
| `LINEAR_HISTORY` (blocks merges) | Removes the `required_linear_history` rule. If it lives in the janitor's own `baseline-history-protect` (the usual case — an older janitor added it), re-applying the corrected baseline drops it. If it lives in a **user-authored** ruleset, the ruleset is PUT back with ONLY that rule removed — every other rule, condition and bypass actor preserved. |
| `UNPROTECTED` | Applies the ratified baseline pair (block force-push + deletion, require a PR with 1 approval). |
| `NO_PR_REVIEW` / `NO_REQUIRED_CHECKS` | The `baseline-pr-and-checks` ruleset (PR review + strict required status checks; CI contexts auto-detected). |
| `NO_TAG_PROTECT` | The `baseline-tag-protect` ruleset (published `vX.Y.Z` tags become immutable). |
| workflow / CI **content** (a vulnerable action, a secret leak) | NOT fixed here — routed to `/janitor-github-workflow-doctor` and `/janitor-security-agent`. |

## Instructions

1. **Resolve the target.** One repo → its `owner/repo` slug. The whole fleet → `--all`.

2. **PLAN (read-only) — always first.** Run WITHOUT `--apply`; it mutates nothing and prints the
   exact per-repo plan:

   ```bash
   # one repo
   uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/github_config_fix.py" --slug <owner/repo>
   # or the whole ai-maestro fleet
   uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/github_config_fix.py" --all
   ```

3. **Show the user the plan and get explicit confirmation.** This step mutates REMOTE repos
   (Tier-2) — do NOT skip it. Summarize which repos change and how.

4. **APPLY — only after the user confirms.** Re-run with `--apply`; it strips linear-history,
   applies the baseline idempotent-by-name, then RE-AUDITS each repo and reports whether every
   finding cleared:

   ```bash
   uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/github_config_fix.py" --slug <owner/repo> --apply
   # or:  … --all --apply
   ```

5. **Report the result** (cleared vs remaining) to the user. Any `remaining after fix` line names
   findings that need the workflow-doctor / security-agent instead.

## CI-context caveat

The required-status-check CONTEXTS are auto-detected from `.github/workflows/` of the LOCAL
checkout, so they are filled in only for the repo whose working tree is the current directory.
For a remote fleet repo you don't have checked out, the checks rule is still installed but gates
on no specific contexts until you re-run this from that repo's checkout. The merge-jam
(linear-history) and unprotected-branch fixes do NOT depend on a local checkout — they work for
every repo.

## Output

Plan mode: the per-repo action list, nothing mutated. Apply mode: per-step results + a
re-audit showing findings cleared. Writes no local files.

## Scope

ONLY changes GitHub branch/tag rulesets on the named plugin repo(s), and only with `--apply`
after confirmation, and only where you are an admin. Does NOT touch local files, does NOT push
code, does NOT disarm the heartbeat. Reuses `branch_protection_lib.apply_baseline_rulesets` (the
same ratified baseline `/janitor-branch-protection-setup` applies).

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/github_config_fix.py` — backing script (plan / --apply).
- `${CLAUDE_PLUGIN_ROOT}/scripts/lib/github_config_audit.py` — the audit + fix helpers.
- `/janitor-branch-protection-setup` — the single-repo baseline applier (this generalises it).
- `/janitor-github-workflow-doctor`, `/janitor-security-agent` — where workflow/CI content
  findings are routed.
