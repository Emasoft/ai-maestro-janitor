---
trdd-id: OHE6WLVM
title: memgrep split-mem-atom cannot split an atom that is one long line
column: backburner
status: tasked
created: 2026-10-06T20:03:46+0200
updated: 2026-10-06T20:03:46+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T20:03:46+0200
---

# memgrep split-mem-atom cannot split an atom that is one long line

Symptom: split-mem-atom splits only at line boundaries, so an oversized atom whose body is a single long line can never be split (example ATOM-ZPD3-6Q6Z, USER scope). 9 oversized atoms remained after the 2026-10-06 split pass (report reports/janitor-memory-subconscious-agent/20261006_200003+0200-split-user.md). Cause: not diagnosed beyond the line-boundary limit. Acceptance: a split of an atom made of one line longer than the size budget either splits it at a sentence or clause boundary or refuses with a clear message naming the limit; after the fix the 9 remaining oversized atoms are split or explicitly reported as unsplittable.

## Approval log

- 2026-10-06T20:03:46+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
