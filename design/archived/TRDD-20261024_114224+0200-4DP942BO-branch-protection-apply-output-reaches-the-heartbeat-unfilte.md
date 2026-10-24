---
trdd-id: 4DP942BO
title: branch_protection_apply output reaches the heartbeat unfiltered
column: complete
status: archived
created: 2026-10-24T11:42:24+0200
updated: 2026-10-24T15:21:29+0200
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
approval-datetime: 2026-10-24T11:42:24+0200
---

# branch_protection_apply output reaches the heartbeat unfiltered

Found by the TRDD-F3LVCQ39 census. dispatch.py:3574-3576 runs scripts/guard/branch_protection_apply.py with capture_output=False, so the child inherits the dispatcher stdout (read in code); not verified that no phase-level redirect applies, so that this reaches the heartbeat output. An interval gate (last-run-guard-branch-protection.ts) bounds how often it runs. Captured detector output goes through _defang_foreign_markers (dispatch.py:1046, applied at :1574 and :1595) so a bare [janitor-...] token cannot act as a heartbeat marker; inherited output skips that. ? That the script prints remote GitHub data was not read. A worker reported four print sites in the script (not read here). ACCEPTANCE: capture its output and route it through the detector pipeline (defang included), with a test that a forged marker in its output is defanged.

## Approval log

- 2026-10-24T11:42:24+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-24T15:19:58+0200 — column → testing by main-agent@ai-maestro-janitor. code landed in d626064f; awaits one live guard run
- 2026-10-24T15:21:29+0200 — COMPLETE by main-agent@ai-maestro-janitor. acceptance met by a real fd-level test that failed before the fix.

## Result (2026-10-24)

Landed in d626064f. stdout is piped and passed through _defang_foreign_markers on the normal and the timeout path; stderr stays inherited, as in _run_detector. Test test_guard_output_markers_are_defanged (capfd) failed on the old code and passes; 331 passed in the three affected files; ruff, mypy and pyright clean. The timeout path is untested (the 60 s timeout is a literal; no mocks).
Deviation from ACCEPTANCE: defang only, not the full detector pipeline, because _dedupe_drift_text would show a repeated apply-FAILED or not-admin security line once a day instead of on every run.
Residual, not covered: stderr is still inherited here and in _run_detector, and branch_protection_lib.py:597 (_trace_soft_fail) writes to stderr. The Bash tool likely shows stderr to the model with stdout (INFERRED), so a forged marker on stderr is a second channel for every detector. Belongs to the F3LVCQ39 census or E17V3KM7, not this card.
Corrections after review: that first_fail[2] is GitHub's error text is INFERRED (the library's message construction was not read); the default branch and CI check names are verified remote. 'Would raise out of the heartbeat' means: not caught by this phase or its call site (dispatch.py:5553); handlers further up were not checked. The stderr residual is now its own card, TRDD-5SDNA4RL.
Closed on the test evidence: the acceptance asked for captured output and a test that a forged marker is defanged; the capfd test failed before and passes after. A live run was not required, because the guard prints only when guard mode and autofix are both on, which may never happen on this host.

## Acceptance checklist

- [x] The guard's stdout is captured, not inherited (d626064f)
- [x] It passes through _defang_foreign_markers on the normal and the timeout path
- [x] A test proves a forged marker in guard output is defanged, and it failed on the old code
