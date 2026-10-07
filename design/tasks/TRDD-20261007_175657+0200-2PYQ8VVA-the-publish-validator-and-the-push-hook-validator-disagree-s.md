---
trdd-id: 2PYQ8VVA
title: The publish validator and the push-hook validator disagree, so a nit fails only after the bump
column: todo
status: tasked
created: 2026-10-07T17:56:57+0200
updated: 2026-10-07T17:56:57+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T17:56:57+0200
---

# The publish validator and the push-hook validator disagree, so a nit fails only after the bump

On 2026-10-07 the 3.8.8 publish's step-4 validator passed card 58Q791FL, but the push hook's validator run refused the push on markdownlint MD028 (blank line between two blockquotes) in that card, after the version bump commit and tags existed locally. Find why the two runs lint different file sets or rules, and make step 4 run exactly what the push hook runs, so a nit fails before the bump. Also: worker briefs that write cards should run markdownlint on the card.

## Approval log

- 2026-10-07T17:56:57+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
