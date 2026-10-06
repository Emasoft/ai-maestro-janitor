---
trdd-id: 4PBW3GV5
title: A heartbeat memory chore can write tracked files while publish.py is running
column: backburner
status: tasked
created: 2026-10-07T00:25:22+0200
updated: 2026-10-07T00:25:22+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T00:25:22+0200
---

# A heartbeat memory chore can write tracked files while publish.py is running

On 2026-10-07 the split chore modified .claude/project/memory/janitor-compaction-floor-gate-triggers.md after publish.py's working-tree check (step 1) had passed and while it was committing and pushing v3.8.1. Harmless this time: the bump commit did not include it and it was committed separately as 5497043b. But the protection was timing, not design.

Options: (a) memory chores yield while a publish holds the tree, via a publish lock the dispatcher checks; (b) publish.py refuses to push if the working tree changed after step 1.

## Approval log

- 2026-10-07T00:25:22+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
