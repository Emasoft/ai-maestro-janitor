---
trdd-id: J4CBUB41
title: bun vault.ts delete may leave the deleted value in vault.db free pages or the WAL
column: backburner
status: tasked
created: 2026-11-18T15:06:14+0100
updated: 2026-11-18T15:21:09+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: security
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-18T15:06:14+0100
---

# bun vault.ts delete may leave the deleted value in vault.db free pages or the WAL

redact-and-restore.md tells the user to remove a leftover vault row with bun vault.ts delete <uuid>. SQLite keeps deleted content in free pages and in the WAL until they are reused or checkpointed, unless PRAGMA secure_delete is on, so the plaintext value can stay readable in vault.db or vault.db-wal after the delete. Check: delete a row, then search vault.db and the WAL bytes for the value. Fix candidates: PRAGMA secure_delete=ON in openVault, plus a WAL checkpoint (TRUNCATE) after delete. Found 2026-11-18 by the harness review of TRDD-JYZAL6HW.

## Approval log

- 2026-11-18T15:06:14+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- Correction on archived TRDD-JYZAL6HW, 2026-11-18T15:07:50+0100, by main-agent (archived cards cannot be edited, so it is recorded here): its COMPLETE line of 2026-11-18T15:06:22+0100 says tests checked. That means test names checked against c6007279 plus a worker-reported run in the commit message; main-agent did not run the tests. Acceptance boxes 1 and 2 rest on those. Box 3 (exits documented in redact-and-restore.md) was checked by main-agent against the Exits section of that file in c6007279: write-error, changed-during-redact and the kill between commit and rename. The bun vault.ts delete verb the card names exists (DELETE FROM secrets in vault.ts) and the doc names it at the same place.
- Correction to the lines of 2026-11-18T15:07:44+0100 and 2026-11-18T15:07:50+0100, 2026-11-18T15:08:51+0100, written by the cheap-worker for main-agent (not a check made by main-agent): (a) main-agent did run test_shield_vault.py (1 passed, per the commit message of c6007279). The earlier phrase main-agent did not run the tests was wrong for that file. The other test names were not run by main-agent; the commit message records a worker run of 100 pytest, 20 bun vault and 7 bun jsonl tests passing. (b) Box 3 was checked by the cheap-worker, not by main-agent: it read the Exits section of skills/janitor-secrets-shield-scan/references/redact-and-restore.md at lines 32 to 40 of the working tree (the same section is added at lines 64 to 70 of the c6007279 doc diff, saved at reports_dev/cheap-worker/cards4/c6007279-doc.diff), and it grepped scripts/shield_scan/vault.ts (DELETE FROM secrets at line 205, the delete command at line 295). The doc names bun vault.ts delete <uuid> at line 40. (c) JYZAL6HW is archived and cannot be corrected in place. Its COMPLETE line says tests checked, and boxes 1 and 2 rest on test names and the commit message, not on a test run. Readers of JYZAL6HW should read this line. The SQLite free-page and WAL retention claim in the card title and body is not verified here.
- Test run, 2026-11-18T15:15:30+0100, by main-agent: tests/test_secrets_shield_redact.py and tests/test_secrets_shield_redact_jsonl.py on the tree after c6007279: 44 passed. This settles item (c) above: JYZAL6HW boxes 1 and 2 now rest on a main-agent test run.
- Stamp note, 2026-11-18T15:21:08+0100, by main-agent: the 15:15:30 stamp of the Test run line is when that line was recorded, not when the tests ran. The run was main-agent's background job of about 15:12 (reports_dev/main-agent/redact-e2e/pytest.txt: 44 passed, exit 0). It ran while this card's worker was editing scripts/shield_scan/vault.ts, so it proves the c6007279 behaviour only together with whatever of that edit was on disk; main-agent re-runs both files after this card's fix lands.
