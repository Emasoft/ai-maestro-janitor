---
trdd-id: QONEBKGK
title: A handoff composed after a janitor clear says idle unknown and context unknown
column: testing
status: tasked
created: 2026-10-05T22:11:18+0200
updated: 2026-10-07T08:11:24+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:18+0200
implementation-commits: [87d754e7, 1799a001, dabcc332, ca45b0e9, 864864ba]
---

# A handoff composed after a janitor clear says idle unknown and context unknown

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

The automatic handoff of 2026-10-05 15:28 carried 'idle unknown, context unknown'. Find why the two measures were unavailable to the composer.

## Approval log

- 2026-10-05T22:11:18+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-07T07:47:58+0200 — column → testing by main-agent@ai-maestro-janitor. implemented in batch B5, awaiting verification
2026-10-07: idle and context are measured from the cleared transcript (87d754e7); a window with no human turn renders a lower bound 'idle >= ~N' instead of unknown (dabcc332, ca45b0e9, merge 864864ba); a sub-hour bound renders in minutes in a follow-up still to merge. Moved to testing by main-agent@ai-maestro-janitor.
2026-10-07: shipped in v3.8.4; release observation starts.
