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

   1b. **Freshness first (issue #69):** this audit reads the plugin CACHE, which can lag the
   installed pin / latest release — findings against a stale cache describe code that is
   no longer live. Print the freshness header and put it at the TOP of the report:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lib/plugin_freshness.py" "${CLAUDE_PLUGIN_ROOT}"
   ```

   If the line carries `⚠ STALE`, say so prominently and recommend updating/reloading the
   plugin BEFORE acting on any finding below (the check is fail-open: `unknown` fields
   mean "could not verify", not "fresh").

2. Run every detector under `${CLAUDE_PLUGIN_ROOT}/scripts/detectors/` once, capturing stdout and stderr separately. Iterate the directory rather than hard-coding a list — that way the skill stays in sync with the dispatcher as detectors are added.

   ```bash
   for d in "${CLAUDE_PLUGIN_ROOT}"/scripts/detectors/*.py; do
     "$d"
   done
   ```

   To guarantee a fresh pass (dedupe seen-files would otherwise silence previously-reported drift), pre-rename each `*-seen.txt` before invoking the detector and restore it afterwards — see Tips.

3. Parse each script's stdout — lines are formatted as `[detector-name] <message>` — and group by detector.

4. Build a single markdown report with one section per detector that produced findings, followed by a summary. Use the detector tag as the section header (e.g. `## PRs`, `## Worktrees`, `## TRDDs`, `## Task/PR mismatches`, `## Stale tasks`, `## Dirty tree`, `## Subagent reports`). For each finding, include the detector's raw line and — when applicable — a proposed remediation command the user can copy-paste.

5. **Retired legacy global-state dir (TRDD-ULEGRT01).** No detector covers this — it is a
   once-per-machine leftover, not recurring drift, so it lives here instead of costing a
   heartbeat check forever:

   ```bash
   LEGACY="$HOME/.claude/janitor-global-state"
   DATA="$HOME/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/global-state"
   if [ -d "$LEGACY" ]; then
     if [ -f "$DATA/migrated-from-legacy.ts" ]; then echo "legacy-state: HANDED OVER, removable"
     else echo "legacy-state: PRESENT, NOT yet handed over — do NOT suggest deleting it"; fi
   fi
   ```

   Report a `## Legacy global state` section ONLY on `HANDED OVER`: nothing reads or writes that
   dir any more, its state was copied into the DATA dir, and its `README-MOVED.txt` explains it —
   so suggest `/janitor-safe-delete ~/.claude/janitor-global-state` (recoverable) and let the
   user decide. **Never delete it yourself** (RULE 0), and stay silent on `NOT yet handed over`:
   the daemon still has a copy to make, and telling the user to delete it first is how state gets
   lost. Absent dir ⇒ nothing to report.

6. Present the report. DO NOT execute any remediation commands — the user must run them explicitly.

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

- `${CLAUDE_PLUGIN_ROOT}/scripts/detectors/` — the drift detector scripts (iterate the directory; do not hard-code the list).
- `${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py` — the cron-fire dispatcher that runs the same detectors on each heartbeat.
- `.janitor/state/` — per-project state directory for deduplication seen-files.

## Tips

- Dedupe files (`$JANITOR_ROOT/state/*-seen.txt`) prevent the same drift from being re-emitted. To force a fresh pass, pre-rename each seen-file aside and restore it after the run — do NOT delete them; the heartbeat relies on them.

- Use the GitHub repo slug from the `github_repo` user config (or `gh repo view --json nameWithOwner -q .nameWithOwner` if unset).

## Scope

This skill READS drift state. It NEVER performs remediation itself. The remediation commands are produced so the user can copy, review, and execute them — or ask you to execute specific ones explicitly.

## Checklist

Copy this checklist and track your progress:

- [ ] Iterate `${CLAUDE_PLUGIN_ROOT}/scripts/detectors/*.py` and run each one
- [ ] Group findings by category (PRs, Worktrees, TRDDs, Task/PR mismatches, Stale tasks, Dirty tree, Subagent reports)
- [ ] Include stderr tail for any detector that returned non-zero
- [ ] Check the retired legacy global-state dir; report it only when it has been handed over
- [ ] Present report with proposed remediation commands (do not execute)
