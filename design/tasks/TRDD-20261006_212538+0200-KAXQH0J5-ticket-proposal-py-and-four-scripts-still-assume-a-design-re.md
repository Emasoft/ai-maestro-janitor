---
trdd-id: KAXQH0J5
title: ticket_proposal.py and four scripts still assume a design/refused folder the owner abolished
column: todo
status: tasked
created: 2026-10-06T21:25:38+0200
updated: 2026-10-06T21:25:38+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:25:38+0200
---

# ticket_proposal.py and four scripts still assume a design/refused folder the owner abolished

Source: GitHub issue Emasoft/ai-maestro-janitor#309 (opened 2026-09-24). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: The owner ruled that a refused card stays in proposals as a column, is never archived by the manager, and that no design/refused zone exists. ticket_proposal.py and four other scripts still assume that zone. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:25:38+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
