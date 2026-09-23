---
trdd-id: N9LDHF7N
title: Jev logs every keep or elide decision and can replay thresholds to tune them
column: todo
created: 2026-09-23T20:17:59+0200
updated: 2026-09-23T20:17:59+0200
current-owner: emanuelesabetta
created-by: emanuelesabetta
task-type: feature
min-approval-requirement: none
assignee: emanuelesabetta
mandate: true
mandated-by: none
approved: true
approval-judge: emanuelesabetta
approval-datetime: 2026-09-23T20:17:59+0200
---

# Jev logs every keep or elide decision and can replay thresholds to tune them

Card 7 of the Jev reference gap analysis (2026-09-23). The relevance and decision thresholds (0.5/0.5) are untuned guesses. Use jevctx.shadow.ShadowLog (vendored 49d733b7): jev_compact.py compact writes one decision per item per question to <project>/.janitor/state/jev-shadow.jsonl (gitignored, project-local: the 200-char previews are transcript content); expand writes an outcome (an expand of an elided id is a false negative); a new replay --threshold T [--question relevance|decision] subcommand prints ShadowStats. Tests: replay is monotonic in the threshold; an expand of an elided id counts as a false negative; the file lands in the state dir, never in the repo tree. Acceptance: after about a week of use, one replay table justifies or changes the thresholds. Depends on card 4.

## Approval log

- 2026-09-23T20:17:59+0200 — MANDATE issued by emanuelesabetta (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
