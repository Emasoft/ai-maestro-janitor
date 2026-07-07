---
trdd-id: LCO8229M
title: S8 — bound the janitor's own FS churn with age-based retention for reports and stale seen-files
column: complete
created: 2026-07-04T04:46:15+0200
updated: 2026-07-07T17:54:11+0200
implementation-commits: [79957c7]
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 4
severity: MEDIUM
effort: S
task-type: feature
parent-trdd: TRDD-ZNN0UK5K
relevant-rules: []
release-via: publish
test-requirements: [unit, lint, typecheck]
labels: [retention, fs-churn, fseventsd-plan]
---

# TRDD-LCO8229M — Janitor FS-churn retention (S8)

## The task

Executes S8 of the fseventsd plan (parent TRDD-ZNN0UK5K). Forensics tied both the disk
pressure and the fsevents volume to high-rate automated FS churn; the janitor contributes
via hundreds of timestamped `reports/<component>/` files and per-project `.janitor/state`
seen-files that are never pruned. The purge pattern already exists (`trashcan-purge`,
`screenshot-purge`) — extend it, don't invent a new one.

## Plan

1. New detector `reports-purge` (or fold into an existing purge detector if cadence
   aligns): age-based retention for `$PROJECT/reports/**` — default keep 30 days
   (`CLAUDE_PLUGIN_OPTION_REPORTS_MAX_AGE_DAYS`, 0 disables), plain `rm` class (reports are
   regeneratable agent output, gitignored by rule — NOT safe-delete/trashcan material,
   which would just move the churn).
2. Stale seen-file trim: for each `.janitor/state/*seen*` file, drop entries older than the
   detector's dedupe horizon (needs per-entry timestamps — where a seen-file is a bare
   hash-set, cap by line count via the existing trim idiom instead).
3. Document retention knobs in CLAUDE.md conventions + the affected skills' docs.

## Derived tasks

- Never purge `reports/` paths that are TRDD-cited evidence younger than the retention
  window — retention age must comfortably exceed the report→TRDD conversion habit; note it.
- Tests: age-boundary purge, opt-out env, empty-dir cleanup, seen-file cap preserves the
  newest entries (dedupe still works after trim).

## Verification

- A fixture tree with old/new reports purges exactly the old ones; disabled env leaves all.
- Steady-state file count in `reports/` + `.janitor/state` stops growing month-over-month.
