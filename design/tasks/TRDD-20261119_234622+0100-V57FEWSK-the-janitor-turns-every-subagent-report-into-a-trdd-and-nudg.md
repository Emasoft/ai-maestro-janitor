---
trdd-id: V57FEWSK
title: The janitor turns every subagent report into a TRDD and nudges the main agent until each is fixed or closed
column: design
status: tasked
created: 2026-11-19T23:46:22+0100
updated: 2026-11-19T23:46:22+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-19T23:46:22+0100
---

# The janitor turns every subagent report into a TRDD and nudges the main agent until each is fixed or closed

Owner directive 2026-11-19 (verbatim): 'the janitor itself should convert subagents reports into TRDDs, and nudge the main agent to fix and complete them.' Also verbatim, same day: 'always convert all issues you report into TRDDs! do not procrastinate fixes! otherwise issues will compound!' and 'convert all issues in TRDDs (including the open issues on github) and fix them all. do not let them compound!'. Today: scripts/detectors/report-to-trdd-drift.py only scans reports/ and only flags filenames matching a decision regex, and only nudges; scripts/detectors/subagent-report.py scans docs_dev, tests/scenarios/reports and scripts_dev for reports not named in a commit. Neither covers reports_dev/<agent>/ (where workers now write), neither creates a card, and neither follows up until the card closes. Needed: (1) on SubagentStop and on each heartbeat, find new subagent reports under reports/ and reports_dev/ that no TRDD cites; (2) mint an intake TRDD per report (title from the report's first heading, body = report path plus its issue lines, column todo, author janitor) unless the report is a no-op/abstain or already cited; (3) heartbeat nudge line listing open intake cards until each is complete, cancelled, or re-columned by the agent; (4) dedupe so one report never makes two cards. Open GitHub issues already map to TRDDs (checked 2026-11-19, all 19 open issues cited by at least one card).

## Approval log

- 2026-11-19T23:46:22+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
