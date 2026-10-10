---
trdd-id: Q9OVLEAQ
title: trddgrep warns that the PRRD carries no project-id field each time a card is created
column: complete
status: archived
created: 2026-10-05T22:08:49+0200
updated: 2026-10-10T15:16:55+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:08:49+0200
---

# trddgrep warns that the PRRD carries no project-id field each time a card is created

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Observed on trddgrep new: 'no project-id: <repo>/design/requirements/PRRD.md carries no project-id field'. The card is still created. To do: decide whether this repository's PRRD should carry the field (the TRDD rule says a project-scope card SHOULD carry project-id) and add it through prrdgrep, or record why not.

## Approval log

- 2026-10-05T22:08:49+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T15:16:55+0200 — COMPLETE by main-agent@ai-maestro-janitor. archived → complete.

## Decision

2026-10-10 15:16, wave 9 card 4: the PRRD now carries project-id: ai-maestro-janitor in its frontmatter, added through prrdgrep edit (one added line; prrdgrep lint clean). The value is the one 154 existing cards of this repository already carry. CAUSE, read in the tool's source (lib/trdd-create.ts of the ai-maestro repository): trddgrep new reads project-id from the PRRD frontmatter to bind a new card and warns when the field is absent. VERIFIED on two scratch corpora by the main session: against the PRRD of the previous commit a minted card prints the warning and carries no project-id; against the edited PRRD it prints no warning and carries project-id: ai-maestro-janitor. NOT DONE: the PRRD's own updated and prrd-version fields were not bumped (the tool did not, and no rule changed); cards minted before today that lack the field are not back-filled.

## Acceptance

- [x] The PRRD carries the field, added through prrdgrep, and a newly minted card binds to it with no warning (checked on a scratch corpus).
