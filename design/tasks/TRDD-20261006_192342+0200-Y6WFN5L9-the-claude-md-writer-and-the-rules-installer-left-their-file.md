---
trdd-id: Y6WFN5L9
title: The CLAUDE.md writer and the rules installer left their files at mode 0600
column: testing
status: tasked
created: 2026-10-06T19:23:42+0200
updated: 2026-10-06T19:23:50+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T19:23:42+0200
implementation-commits: [1edf766d, 113121d2]
---

# The CLAUDE.md writer and the rules installer left their files at mode 0600

scripts/repomap_generate.py _atomic_replace (every project's CLAUDE.md wikimem index block) and scripts/lib/rules_installer.py _publish_monotonic (rule files under the user's .claude/rules) wrote through tempfile.mkstemp (0600) then os.replace, which keeps that mode. Fixed in 1edf766d and 113121d2: the temp file gets the target's existing mode, or 0644 when the target is absent or exactly 0600 (a deliberately-0600 file cannot be told apart and is widened; stated trade-off). Measured 2026-10-06: 15 of 24 installed rule files were at 0600; they heal only when a rule's version stamp next advances. OPEN: 41 tracked files in this repo were at 0600 (restored to 0644; list in reports/file-modes/, gitignored); the janitor explains CLAUDE.md only; the writer of the other ~40 source and test files is unknown (fastedit simple paths tested clean; its merge, retry and undo paths untested).

## Approval log

- 2026-10-06T19:23:42+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## STATE

2026-10-06 NEXT ACTION: none on code. NAMED LIVE CHECK after the release carrying 113121d2 (v3.7.5): the next CLAUDE.md index refresh leaves the file at its previous mode (not 0600), and a rule file reinstalled at a new version is 0644. Open question above stays with TRDD-6NMQ95TQ.
