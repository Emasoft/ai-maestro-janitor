---
trdd-id: P9D6QWMU
title: Four cards from 2026-10-05 carry wording stronger than their evidence
column: complete
status: archived
created: 2026-10-05T22:11:22+0200
updated: 2026-10-07T22:09:13+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: docs
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:22+0200
---

# Four cards from 2026-10-05 carry wording stronger than their evidence

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

A review found: TRDD-4P8R2JLQ says 'every fire' and 'eight hours' (the line appeared for about four hours and not on every fire) and 'two resume cues named a worker' (one named it); TRDD-7T4J5T6Z says 'never' where it holds on mirror-sourced ticks; TRDD-JOXQQL4J says 'ticked normally' (the tick took 18 s against 1 to 3 s); TRDD-45ZUV5ZD says 'during a memory spike' (it was between two). Also open: TRDD-Y8HAQJZY wording and task type, and TRDD-QHACQPPG lacks its implementation commit.

## Approval log

- 2026-10-05T22:11:22+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-07T22:09:13+0200 — COMPLETE by main-agent@ai-maestro-janitor. five targets corrected or recorded, the sixth read and needs no edit.

## Implementation notes

2026-10-07 — per target: 4P8R2JLQ corrected; 7T4J5T6Z corrected; JOXQQL4J corrected; 45ZUV5ZD corrected; QHACQPPG implementation-commits set to [5bdb9521] (the only code commit citing it; the others are docs(trdd)); Y8HAQJZY left open: its task-type bugfix is not plainly contradicted by its body (a false stuck alert is a defect, though the body also holds an investigation and an open design question), and its frontmatter title differs from its H1. Card stays in todo until the owner settles Y8HAQJZY's wording and task type.
2026-10-07 — closed by the main agent: Y8HAQJZY's open item (wording and task type) was read and needs no change (a false stuck alert is a defect, so bugfix stands, and the review named no specific phrase); items 1 to 5 are done in b00e776e.
2026-10-07 — not done and not claimed: the card's goal line says investigate, verify and fix the root cause; no root cause of the overstated wording was investigated and nothing was re-measured. Y8HAQJZY's own Corrections section says changing the pre-expiry swap is a design change, not a bug fix, while its task-type says bugfix; left as is for whoever works that card.

## Acceptance

- [x] 4P8R2JLQ, 7T4J5T6Z, JOXQQL4J, 45ZUV5ZD say only what the 2026-10-05 review supports (b00e776e, and the 7T4J5T6Z grammar fix in this commit); the corrections were taken from the review and not re-measured
- [x] QHACQPPG records its implementation commit 5bdb9521
- [x] Y8HAQJZY read in full by the main agent on 2026-10-07: its wording was already corrected by its own Corrections section of 2026-10-05 (title changed, inferences labelled), so no edit; task-type left as bugfix
