---
name: janitor-audit
description: Runs an on-demand audit of open PRs, git worktrees, TRDD drift, and task/PR mismatches. Use when the user asks "janitor audit", "what's drifted?", or "audit pending things". Trigger with `/janitor-audit` or by asking for a janitor audit report.
---

# Janitor audit

## Overview

Invokes each ai-maestro-janitor detector synchronously, aggregates output into a single markdown report, and proposes — but does not execute — remediation commands for each drift item found. Independent of the heartbeat cron armed by `/janitor-arm`: this skill runs the same detectors on demand.

## Prerequisites

- `ai-maestro-janitor` plugin installed, detectors present at `${CLAUDE_PLUGIN_ROOT}/scripts/detectors/`.
- Project has a `.janitor/state/` directory (created automatically on first run).
- `gh` CLI authenticated (for GitHub repo slug lookup if `github_repo` userConfig is unset).

## Instructions

1. Resolve `JANITOR_ROOT` = `${CLAUDE_PROJECT_DIR}/.janitor` (fall back to `$(pwd)/.janitor` if the env var is unset).

2. Run each detector once, capturing stdout and stderr separately. To guarantee a fresh pass (the dedupe seen-files would otherwise silence previously-reported drift), pre-rename each `*-seen.txt` file before invoking the detector and restore it afterwards — see Tips.

   ```
   ${CLAUDE_PLUGIN_ROOT}/scripts/detectors/pr-reconciler.sh
   ${CLAUDE_PLUGIN_ROOT}/scripts/detectors/worktree-janitor.sh
   ${CLAUDE_PLUGIN_ROOT}/scripts/detectors/trdd-drift.sh
   ${CLAUDE_PLUGIN_ROOT}/scripts/detectors/trdd-reminder.sh
   ${CLAUDE_PLUGIN_ROOT}/scripts/detectors/task-pr-mismatch.sh
   ```

3. Parse each script's stdout — lines are formatted as `[detector-name] <message>` — and group by detector.

4. Build a single markdown report of this shape:

   ```markdown
   # Janitor audit — <ISO timestamp>

   ## PRs (N findings)
   - PR #10 '<title>' — HEAD abcd1234 is already on main. Close with:
     `gh pr close 10 --repo <repo> --delete-branch --comment "superseded"`

   ## Worktrees (N findings)
   - /path/to/wt — branch 'foo' is merged. Prune with:
     `git worktree remove /path/to/wt && git branch -d foo`

   ## TRDDs (N findings)
   - TRDD-abc12345 'Mesh chat' — In progress, untouched 34 days. Review: `code design/tasks/TRDD-abc12345-*.md`

   ## Task/PR mismatches (N findings)
   - Task #143 marked completed but PR #11 is still open. Reconcile the task status or close the PR.

   ## Summary
   - Total drift items: N
   - High-confidence close candidates: M
   ```

5. Present the report. DO NOT execute any remediation commands — the user must run them explicitly.

## Output

A single markdown audit report grouping findings by category (PRs, Worktrees, TRDDs, Task/PR mismatches) with proposed remediation commands. No commands are executed.

## Error Handling

- If a detector returns non-zero exit status, include the stderr log tail in the report so the user can diagnose.
- If a detector has no output, state "No drift detected" for that category rather than leaving the section blank.
- If `${CLAUDE_PLUGIN_ROOT}` is unset, abort with a clear message asking the user to verify the plugin is installed.

## Examples

```
User: run the janitor audit
User: what's drifted?
User: janitor audit
User: audit pending PRs and worktrees
```

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/detectors/` — the five drift detector scripts.
- `${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.sh` — the cron-fire dispatcher that runs the same detectors on each heartbeat.
- `.janitor/state/` — per-project state directory for deduplication seen-files.

## Tips

- The detectors' dedupe files (`$JANITOR_ROOT/state/*-seen.txt`) prevent the same drift from being re-emitted. If a prior heartbeat fire already saw the drift, the detector will stay silent on this audit. To guarantee a fresh pass, pre-rename the seen-files:

  ```bash
  mv "$JANITOR_ROOT/state/pr-reconciler-seen.txt" "$JANITOR_ROOT/state/pr-reconciler-seen.txt.bak"
  <run detector>
  mv "$JANITOR_ROOT/state/pr-reconciler-seen.txt.bak" "$JANITOR_ROOT/state/pr-reconciler-seen.txt"
  ```

  Do NOT delete the original seen-files — the heartbeat relies on them.

- Use the GitHub repo slug from the `github_repo` user config (or `gh repo view --json nameWithOwner -q .nameWithOwner` if unset).

## Scope

This skill READS drift state. It NEVER performs remediation itself. The remediation commands are produced so the user can copy, review, and execute them — or ask you to execute specific ones explicitly.

## Checklist

Copy this checklist and track your progress:

- [ ] Run all five detectors in sequence
- [ ] Group findings by category (PRs, Worktrees, TRDDs, Task/PR mismatches)
- [ ] Include stderr tail for any detector that returned non-zero
- [ ] Present report with proposed remediation commands (do not execute)
