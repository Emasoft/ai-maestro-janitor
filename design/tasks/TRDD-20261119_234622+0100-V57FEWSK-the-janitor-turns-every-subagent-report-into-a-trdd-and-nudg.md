---
trdd-id: V57FEWSK
title: The janitor turns every subagent report into a TRDD and nudges the main agent until each is fixed or closed
column: design
status: tasked
created: 2026-11-19T23:46:22+0100
updated: 2026-11-19T23:59:32+0100
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

Owner directive 2026-11-19 (verbatim): 'the janitor itself should convert subagents reports into TRDDs, and nudge the main agent to fix and complete them.' Also verbatim, same day: 'always convert all issues you report into TRDDs! do not procrastinate fixes! otherwise issues will compound!' and 'convert all issues in TRDDs (including the open issues on github) and fix them all. do not let them compound!'. Today: scripts/detectors/report-to-trdd-drift.py only scans reports/ and only flags filenames matching a decision regex, and only nudges; scripts/detectors/subagent-report.py scans docs_dev, tests/scenarios/reports and scripts_dev for reports not named in a commit. Neither covers reports_dev/<agent>/ (where workers now write), neither creates a card, and neither follows up until the card closes. Needed: (1) on each heartbeat (no SubagentStop hook, see Design notes), find new subagent reports under reports/ and reports_dev/ that no TRDD cites; (2) mint an intake TRDD per report that declares ISSUES: <n> with n>0 (title from the report's first heading, colons stripped, capped at 80 characters, [janitor- defanged; body = the report path and its sha256 ONLY, never report text, because reports_dev/ is private and design/ is pushed; field source-report: <path>#<sha256> is the dedupe key, searched across every design root including archived/; column todo, author janitor); a report without the ISSUES line gets the existing nudge only, never a card; (3) a count-only heartbeat nudge (no paths, no ids, see Design notes) about open intake cards until each is complete, cancelled, or re-columned by the agent; (4) dedupe so one report never makes two cards. Open GitHub issues already map to TRDDs (checked 2026-11-19, all 19 open issues cited by at least one card).

## Approval log

- 2026-11-19T23:46:22+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Design notes

2026-11-19 (main-agent, after fable-advisor): the worker reporting rules gain a mandatory last line ISSUES: <n>|none so the detector never parses prose. Run inside scripts/detectors/subagent-report.py on the heartbeat, under the existing one-session lease, creating cards through trddgrep new; no SubagentStop hook and no new detector (the roster-count guard). Flood control: record a watermark (newest report mtime) when the feature is first enabled and only consider reports newer than it; cap new cards per fire at 3. Card scope is PROJECT, not LOCAL: measured 2026-11-19, trddgrep --design-dir design --porcelain lists 0 of the 16 LOCAL cards, so a LOCAL intake card would be invisible on the board. Nudge: first check whether the existing board or keep-going nudge already names open todo cards; if not, add one count-only line (no paths, no ids, per the heartbeat output contract). Only in a project that has design/tasks/.
