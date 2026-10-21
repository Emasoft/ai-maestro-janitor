---
trdd-id: EKZ44CDZ
title: The version-update trigger must fire and finish inside a two-minute publish-to-install window
column: todo
status: tasked
created: 2026-10-21T19:08:28+0200
updated: 2026-10-21T19:08:28+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: infra
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-21T19:08:28+0200
---

# The version-update trigger must fire and finish inside a two-minute publish-to-install window

Split out of TRDD-R8DRK3DG, whose retention half landed in 5b6d64ef, d324613d and 74091e3a. The remaining half: the janitor's self-update trigger bound (detector poll 300 s, plus the daemon consuming the request flag, plus up to about 120 s for claude plugin update, so about 7 minutes worst case) exceeds the 128 s publish-to-install interval observed on 2026-10-07. While that holds, a silent daemon-version-update.log for such a window is uninformative: the path could not have fired and finished in time. ACCEPTANCE: either the trigger-to-install-completion bound is shown (by a test or a measured run) to be under the publish-to-install interval it must explain, or the card records with evidence that the bound cannot be met and how box 2 of TRDD-A70YJLXN is decided without it. Also open: _consume_version_update_request writes no line of its own (the terminal line's timestamp bounds it).

## Approval log

- 2026-10-21T19:08:28+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
