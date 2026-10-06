---
trdd-id: 1T0W2ZVW
title: Per-scope lock and ledger of lint --apply-fixes are untested on a real memory root
column: backburner
status: tasked
created: 2026-10-06T21:00:47+0200
updated: 2026-10-06T21:00:47+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:00:47+0200
---

# Per-scope lock and ledger of lint --apply-fixes are untested on a real memory root

Found by the C22 S6 check (TRDD-JD2QR5SQ). write_gate::scope_root_for did not recognise the scratch copies as scopes, so every page used the shared memory-maint-out-of-scope lock and its ledger, memory-maint-out-of-scope.unfixed.tsv. On real roots the lock and the ledger should be per scope; that path has not been exercised. Also: all unrecognised roots share one ledger. Acceptance: run lint --apply-fixes on a real scope (or a scratch copy that scope_root_for recognises, with every state and scope variable pointed at scratch) and record which lock file and ledger file are used.

## Approval log

- 2026-10-06T21:00:47+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
