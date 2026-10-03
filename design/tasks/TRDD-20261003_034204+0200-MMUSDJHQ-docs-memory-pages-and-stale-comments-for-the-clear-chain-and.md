---
trdd-id: MMUSDJHQ
title: Docs, memory pages and stale comments for the clear chain and rotator
column: todo
status: tasked
created: 2026-10-03T03:42:04+0200
updated: 2026-10-03T03:45:47+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: docs
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: manager
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-03T03:42:04+0200
project-id: ai-maestro-janitor
parent-trdd: K9AHY1ZB
derived: true
---

# Docs, memory pages and stale comments for the clear chain and rotator

### C7 (part 1)
- Correct memory ATOM-RQDO-2SJE ("UNREADABLE is the designed path").
- Update the `jev-compaction` and `janitor-compaction-floor-gate*` pages (hold contract).
- Update `skills/janitor-compact-context/SKILL.md`: stale `:240` reference; `--force` does not pass the floor.
- **Verify**: `memgrep validate <page> && memgrep lint <page>` reports 0 errors.

Parent plan: TRDD-K9AHY1ZB

## Approval log

- 2026-10-03T03:42:04+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
