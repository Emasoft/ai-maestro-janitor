---
trdd-id: S41TV0I7
title: Pending memory-maint records of kinds the drain cannot judge have no way out of the queue
column: todo
status: tasked
created: 2026-10-10T08:17:30+0200
updated: 2026-10-10T08:17:30+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-10T08:17:30+0200
---

# Pending memory-maint records of kinds the drain cannot judge have no way out of the queue

Split from TRDD-K5F7US68 box 5 on 2026-10-10. FACTS: memory_dispatch_claim.is_drained drops an aged-out pending record only when candidates_for gives a known empty answer; candidates_for answers unknown for enrich and relocate (they shell out to memgrep lint) and retro-lesson has no candidate function, so a record of those kinds stays claimable for ever. This repo holds two from 2026-09-03: retro-lesson PROJECT (its root is the live PROJECT corpus through the old path alias) and enrich LOCAL (root is the old path's slug directory, which still exists). claim_one takes the oldest matching record first, so the next enrich fire in this project would work the old slug directory. A 30-day expiry for every kind was proposed and dropped after review on 2026-10-10: it contradicts the rule in is_drained that an unknown answer keeps the record, and nobody has read how enrich and retro-lesson are re-emitted. TO DO FIRST: read the emit paths of enrich, relocate and retro-lesson in scripts/detectors/memory-maintenance.py and say whether a dropped record is regenerated when work remains; then decide between an expiry, a strict candidate answer for those kinds, or a recorded keep. Acceptance: the two 2026-09-03 records are either consumed, expired by a rule with a test, or kept with a reason that names the code read.

## Approval log

- 2026-10-10T08:17:30+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
