---
name: janitor-audit
description: Runs an on-demand audit of open PRs, git worktrees, TRDD drift, and task/PR mismatches. Use when the user asks "janitor audit", "what's drifted?", or "audit pending things". Trigger with `/janitor-audit` or by asking for a janitor audit report.
---

# Janitor audit

## Overview

Invokes each ai-maestro-janitor monitor in `--one-shot` mode, aggregates output into a single markdown report, and proposes — but does not execute — remediation commands for each drift item found.

## Prerequisites

- `ai-maestro-janitor` plugin installed and monitors present at `${CLAUDE_PLUGIN_ROOT}/scripts/monitors/`
- Project has a `.janitor/state/` directory (created automatically on first run)
- `gh` CLI authenticated (for GitHub repo slug lookup if `github_repo` userConfig is unset)

## Instructions

1. Resolve `JANITOR_ROOT` = `${CLAUDE_PROJECT_DIR}/.janitor` (fall back to `$(pwd)/.janitor` if the env var is unset).

2. Run each drift-detection monitor in one-shot mode, capturing stdout and stderr separately. Do NOT rely on the monitors' seen-files — pass `--one-shot --fresh` semantics by temporarily redirecting the seen-file env (see Tips). Each run is a single synchronous pass.

   ```
   ${CLAUDE_PLUGIN_ROOT}/scripts/monitors/pr-reconciler.sh --one-shot
   ${CLAUDE_PLUGIN_ROOT}/scripts/monitors/worktree-janitor.sh --one-shot
   ${CLAUDE_PLUGIN_ROOT}/scripts/monitors/trdd-drift.sh --one-shot
   ${CLAUDE_PLUGIN_ROOT}/scripts/monitors/trdd-reminder.sh --one-shot
   ${CLAUDE_PLUGIN_ROOT}/scripts/monitors/task-pr-mismatch.sh --one-shot
   ```

3. Parse each script's stdout — lines are formatted as `[monitor-name] <message>` — and group by monitor.

4. Build a single markdown report of this shape:

   ```markdown
   # Janitor audit — <ISO timestamp>

   ## PRs (N findings)
   - PR #10 '<title>' — HEAD abcd1234 is already on main. Close with:
     `gh pr close 10 --repo <repo> --delete-branch --comment "superseded"`
   ...

   ## Worktrees (N findings)
   - /path/to/wt — branch 'foo' is merged. Prune with:
     `git worktree remove /path/to/wt && git branch -d foo`
   ...

   ## TRDDs (N findings)
   - TRDD-abc12345 'Mesh chat' — In progress, untouched 34 days. Review: `code design/tasks/TRDD-abc12345-*.md`
   ...

   ## Task/PR mismatches (N findings)
   - Task #143 marked completed but PR #11 is still open. Reconcile the task status or close the PR.
   ...

   ## Summary
   - Total drift items: N
   - High-confidence close candidates: M
   ```

5. Present the report. DO NOT execute any of the remediation commands — the user must run them explicitly.

## Output

A single markdown audit report grouping findings by category (PRs, Worktrees, TRDDs, Task/PR mismatches) with proposed remediation commands. No commands are executed.

## Error Handling

- If a monitor returns non-zero exit status, include the stderr log tail in the report so the user can diagnose.
- If a monitor has no output, state "No drift detected" for that category rather than leaving the section blank.
- If `${CLAUDE_PLUGIN_ROOT}` is unset, abort with a clear message asking the user to verify the plugin is installed.

## Examples

```
User: run the janitor audit
User: what's drifted?
User: janitor audit
User: audit pending PRs and worktrees
```

The skill runs all five monitors and returns a consolidated report. The user then decides which remediation commands to execute.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/monitors/` — the five drift-detection monitor scripts
- `${CLAUDE_PLUGIN_ROOT}/scripts/hooks/` — the four lifecycle hook scripts
- `.janitor/state/` — per-project state directory for deduplication seen-files

## Tips

- The monitors' dedupe files (`$JANITOR_ROOT/state/*-seen.txt`) prevent the same drift from being re-emitted in the running-background path. In one-shot mode, if a previous run already saw the drift, the monitor will stay silent. To guarantee a fresh pass, pre-rename the seen-files:
  ```bash
  mv "$JANITOR_ROOT/state/pr-reconciler-seen.txt" "$JANITOR_ROOT/state/pr-reconciler-seen.txt.bak"
  <run monitor>
  mv "$JANITOR_ROOT/state/pr-reconciler-seen.txt.bak" "$JANITOR_ROOT/state/pr-reconciler-seen.txt"
  ```
  Do NOT delete the original seen-files — the running monitors rely on them.

- Always use the exact GitHub repo slug from the `github_repo` user config (or `gh repo view --json nameWithOwner -q .nameWithOwner` if unset).

## Scope

This skill READS drift state. It NEVER performs remediation itself. The remediation commands are produced so the user can copy, review, and execute them — or ask you to execute specific ones explicitly.

## Checklist

Copy this checklist and track your progress:

- [ ] Run all five monitors in `--one-shot` mode
- [ ] Group findings by category (PRs, Worktrees, TRDDs, Task/PR mismatches)
- [ ] Include stderr tail for any monitor that returned non-zero
- [ ] Present report with proposed remediation commands (do not execute)
