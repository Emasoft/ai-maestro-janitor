---
trdd-id: MMUSDJHQ
title: Docs, memory pages and stale comments for the clear chain and rotator
column: todo
status: tasked
created: 2026-10-03T03:42:04+0200
updated: 2026-10-03T05:09:48+0200
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
implementation-commits: [bfefa9f8]
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

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-03

2026-10-03: bfefa9f8 (exec-bit sweep + derived test) is attributed here.
RELEASE BLOCKERS (fastedit refused, owner asked about a one-off plain edit): delete the four stale comment lines in scripts/clear_trigger.py saying a failed hold write must stop the chain (superseded by the fail-open in take_summary_hold, a48d8974); delete the unused constant _LATE_SUMMARY_STAMP in scripts/dispatch.py.
