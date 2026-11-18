---
trdd-id: JYZAL6HW
title: a shield-scan redact skip after the vault step leaves the values of an unwritten file in the vault
column: backburner
status: tasked
created: 2026-11-18T08:56:20+0100
updated: 2026-11-18T10:17:14+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-18T08:56:20+0100
parent-trdd: BAQB9SYO
---

# a shield-scan redact skip after the vault step leaves the values of an unwritten file in the vault

Found 2026-11-18 by main-agent while reading scripts/shield_scan/worker.ts redactFile: each round calls vault.lookupOrInsert(real, entries) before the restore check, the JSONL broken-line check and the next round's plan, so a file skipped at any of those points (align-error, json-broken) is never written while its secret values stay as plain rows in the vault. In the real-data acceptance run of 2026-11-18 (BAQB9SYO, line of 08:51:32) one transcript was skipped as align-error in round 2; by the code (round 1 calls lookupOrInsert before round 2 plans), its round-1 values were vaulted, which was not checked in the vault itself. Restore never reads those rows (no marker points at them), so nothing is lost, but the vault holds plaintext secrets of a file the run reports as not redacted. Fix to decide: run every check of a round before the vault write (the restore check would then use the planned values, not the rows), or delete the rows a skipped file inserted, in the same transaction. Test: a file that fails a late check leaves 0 new rows in a temporary vault.

## Approval log

- 2026-11-18T08:56:20+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Decision

- Decision, 2026-11-18T10:20:00+0100, by main-agent under the owner ruling to decide alone: not fixed in 3.9.9; the gap is documented in skills/janitor-secrets-shield-scan/references/redact-and-restore.md (Redact details). A leftover row repeats a value that the skipped file still holds in plain text, while a cleanup that deletes the wrong row leaves a marker that can never be restored, so the fix waits for its own careful change, after 3.9.9 and before the report-sanitizer scanner pin. Chosen fix: write the vault after every check of the file, not before (restoreCheck already takes a lookup callback, worker.ts line 122), so no exit leaves rows; deleting rows after a skip cannot reach the per-file time limit kill, which is the skip that fired in acceptance 2 pass 1. Exits after the first vault write today: restoreCheck, brokenLines, both next-plan-null branches, the two home-pass skips, checkWriteTarget, a write that is not written, a VaultError in a later round, and the time-limit kill. Tests: a file that fails a late check leaves 0 new rows; a file that already holds markers and fails a late check still restores its old markers; check PRAGMA secure_delete and the WAL so that no deleted value stays in vault.db.
- Stamp correction, 2026-11-18T10:16:30+0100, by main-agent: the stamp 10:20:00 of the Decision line above was typed, not read from the clock; the line was appended at 10:07:13 (the updated: value after the append, read from git).
