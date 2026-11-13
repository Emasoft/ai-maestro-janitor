---
trdd-id: 1T0W2ZVW
title: Per-scope lock and ledger of lint --apply-fixes are untested on a real memory root
column: complete
status: archived
created: 2026-10-06T21:00:47+0200
updated: 2026-11-13T20:30:12+0100
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
implementation-commits: [610f569c]
---

# Per-scope lock and ledger of lint --apply-fixes are untested on a real memory root

Found by the C22 S6 check (TRDD-JD2QR5SQ). write_gate::scope_root_for did not recognise the scratch copies as scopes, so every page used the shared memory-maint-out-of-scope lock and its ledger, memory-maint-out-of-scope.unfixed.tsv. On real roots the lock and the ledger should be per scope; that path has not been exercised. Also: all unrecognised roots share one ledger. Acceptance: run lint --apply-fixes on a real scope (or a scratch copy that scope_root_for recognises, with every state and scope variable pointed at scratch) and record which lock file and ledger file are used.

## Approval log

- 2026-10-06T21:00:47+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-13 — closing evidence: commit 610f569c cli.rs test covers the card acceptance (see STATE); cargo test --test cli lint_apply_fixes 9 passed. Closed by main-agent@ai-maestro-janitor. Contention and real-root observation stay with TRDD-JD2QR5SQ.
- 2026-11-13T20:30:12+0100 — COMPLETE by main-agent@ai-maestro-janitor. acceptance met by 610f569c test, see STATE.

## STATE

2026-11-13: ACCEPTANCE MET by commit 610f569c (2026-10-07, test only, no production change): scripts/memgrep/tests/cli.rs lint_apply_fixes_on_a_recognised_scope_uses_the_per_scope_lock_and_ledger runs the real memgrep binary with lint --apply-fixes on a scratch dir named memory (recognised by scope_root_for), every state and scope variable pointed at scratch, and asserts the lock is memory-maint-<sha256(canonical root)[..16]>.lock, the ledger has the same stem with .unfixed.tsv, no memory-maint-out-of-scope.lock exists, exactly one ledger line for the one refused page, and the safe page is fixed. Re-run 2026-11-13: cargo test --test cli lint_apply_fixes -> 9 passed 0 failed (includes this test). The card asked only to record which lock and ledger files are used; the test and its commit message record exactly that. NOT covered and never in this card acceptance: exclusion under concurrent contention, and an observation on a real (non-scratch) root; those remain unproven and belong to the field gate of TRDD-JD2QR5SQ.

## Acceptance

- [x] lint --apply-fixes on a recognised scope (scratch dir named memory, state and scope variables at scratch) records which lock and ledger files are used: per-scope memory-maint-<sha16>.lock and .unfixed.tsv, no out-of-scope fallback (commit 610f569c, cli.rs test)
