---
trdd-id: 7IUTRX29
title: S3+S4 — audit every self-heal loop for boundedness and every append-log for rotation
column: complete
created: 2026-07-04T04:46:15+0200
updated: 2026-07-07T18:08:44+0200
implementation-commits: [aa789c7]
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 4
severity: MEDIUM
effort: M
task-type: audit
parent-trdd: TRDD-ZNN0UK5K
relevant-rules: []
release-via: publish
test-requirements: [unit, lint, typecheck]
labels: [boundedness, log-rotation, fseventsd-plan]
---

# TRDD-7IUTRX29 — Self-heal boundedness + append-log rotation audit (S3+S4)

## The task

Executes S3+S4 of the fseventsd plan (parent TRDD-ZNN0UK5K). The runaway's second
ingredient was an unbounded self-heal (`verify_or_restage` re-copying every boot with no
backoff). Sweep the janitor for the same shape and for unrotated append-logs, then fix the
gaps. Invariant to document: "a self-heal that can run every tick MUST dedupe/back-off on
an unchanged input"; "every append site MUST rotate or trim".

## Plan

- **S3 (boundedness sweep):** audit the daemon task loop, `memory_txn.resume_pending`,
  `cache_prune`, the fleet-recovery rungs (`fleet_recovery.gate` cooldowns), and
  `version_update` auto-rollback for act-in-a-loop-without-convergence-guard. Mostly audit;
  add cooldown/dedupe ONLY where a hot path lacks one. Write the invariant into CLAUDE.md's
  conventions section.
- **S4 (rotation sweep):** verify `rotate_log_if_big`, `token_meter.trim_log`,
  `recovery_audit.trim_recovery_audit` coverage; add rotation to the known gaps — `dedupe`
  seen-files, `version_update_lib` update log, `janitor_self_integrity.AuditChain` (chained
  log: trim must preserve chain verifiability — trim from the head, re-anchor), and any
  `state.log_line` consumer without `rotate_log_if_big`.

## Derived tasks

- AuditChain trim needs its own design note: naive truncation breaks HMAC chaining —
  re-anchor on trim + a test proving `verify()` still passes post-trim.
- Per added backoff: a unit test proving ≤1 side-effecting action per cooldown window on
  unchanged input.

## Verification

- Report enumerating every audited loop/log with verdict (bounded/rotated | fixed | n/a).
- New tests green; no append-log in `.janitor/`/global-state can grow unbounded.
