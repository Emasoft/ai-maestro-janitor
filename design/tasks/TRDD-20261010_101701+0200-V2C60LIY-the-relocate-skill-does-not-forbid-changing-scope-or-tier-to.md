---
trdd-id: V2C60LIY
title: The relocate skill does not forbid changing scope or tier to get past a refused page mint
column: backburner
status: tasked
created: 2026-10-10T10:17:01+0200
updated: 2026-10-10T10:17:01+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-10T10:17:01+0200
---

# The relocate skill does not forbid changing scope or tier to get past a refused page mint

Residue of TRDD-BAK8B3C0, which is complete and frozen; carded 2026-10-10 so the gaps keep an open owner. FIELD CASE UNOBSERVED for every item.

From the review of 6506bd61, in skills/janitor-memory-relocate/SKILL.md, CREATE section, step 3: (1) the skill forbids changing the page NAME to get past a refused new-mem-topic, but not --scope or --tier; a changed scope would mint the page in another root, a near-duplicate; (2) 'record any other refusal' can be read as covering the already-exists case too, skipping the re-survey; (3) what to do when the one description re-run is refused again is implied, not stated; (4) step 4 (the move) is only implicitly skipped after a recorded refusal; (5) an atom whose mint was refused stays off-topic until a human reads the report, nothing automated follows up; (6) the once-only bound, the name ban and the position of the record-the-empty-survey sentence are not pinned by a test; (7) how memgrep recall matches a topic was never read.

DATED REASON FOR BACKBURNER: no live relocate pass has met a refused mint; four code commits were already spent on this unobserved race. Pull this card when a relocate report shows an agent misreading the paragraph, and then fix all items in one edit with one phrase-pin per rule.

## Acceptance

- [ ] A live relocate report showing a misread is quoted here, or the card is closed as not needed with the reason
- [ ] The paragraph is rewritten once and each rule in it has a phrase-pin test

## Approval log

- 2026-10-10T10:17:01+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
