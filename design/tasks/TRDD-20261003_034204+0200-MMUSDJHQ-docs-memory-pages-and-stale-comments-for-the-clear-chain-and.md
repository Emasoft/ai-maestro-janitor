---
trdd-id: MMUSDJHQ
title: Docs, memory pages and stale comments for the clear chain and rotator
column: todo
status: tasked
created: 2026-10-03T03:42:04+0200
updated: 2026-10-03T07:36:08+0200
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

## Process breaches to record

- A worker edited a Python file with a script instead of fastedit.
- A worker used the plain Edit tool once.
- A worker ran sed -i on a test file.
- The main session passed two -F files to git commit, so e9b7622d lost its subject and card id (fixed by message-only follow-up 346a557d, no history rewrite).
- Fastedit-refused leftovers still pending an owner-approved plain edit: a stale comment in scripts/clear_trigger.py, the _LATE_SUMMARY_STAMP constant in scripts/dispatch.py, R4b dead code in scripts/lib/rotator_alert.py.
The main session probed the privacy scanner with a real git commit (message probe); only the block stopped a junk commit. Probe with the scanner script or git commit --dry-run instead.
The main session told a worker to remove every at-sign from a card instead of only the flagged line, so audit lines were rewritten (b2b05926, restored next commit). Scope a scanner fix to the flagged line only.
