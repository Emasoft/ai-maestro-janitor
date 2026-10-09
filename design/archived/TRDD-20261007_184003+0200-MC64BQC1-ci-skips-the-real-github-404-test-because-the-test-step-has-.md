---
trdd-id: MC64BQC1
title: CI skips the real GitHub 404 test because the test step has no gh token
column: complete
status: archived
created: 2026-10-07T18:40:03+0200
updated: 2026-10-09T23:18:58+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: infra
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T18:40:03+0200
implementation-commits: [7f8c27af, 29c685a4]
---

# CI skips the real GitHub 404 test because the test step has no gh token

The memgrep-binary-stale test test_real_404_has_its_own_reason calls GitHub for real and skips when gh has no login (559f6102), which is the case on the CI runner. So CI does not check the not-on-GitHub path. Fix: pass the workflow token to the CI Tests step (env GH_TOKEN set to the GITHUB_TOKEN of the run, permission contents read is enough for compare on a public repo), then confirm in the CI log with pytest -rs that the test runs instead of skipping. Found 2026-10-07 after 3.8.8's CI failed on it.

## Approval log

- 2026-10-07T18:40:03+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-10-09 CLOSED by the main session (board drain, wave 3). Checked by the main session itself: fix commits are ancestors of the v3.8.11 tag; the card's tests pass on a re-run today. Field: the card's own pending observation is found: in CI run 37686495589 (v3.8.11) the pytest -rs skip list names lines 108, 116, 130 and 209 of tests/test_memgrep_binary_stale.py and NOT line 185, the real-404 test, with 18094 passed; read with gh run view --log by the main session. Inferred from the skip list, not from a PASSED line. Assessment: reports/board/20261009_231529+0200-wave3-batchA.md.
- 2026-10-09T23:18:58+0200 — COMPLETE by main-agent@ai-maestro-janitor. released in v3.8.11; tests re-run; see Approval log 2026-10-09.

## Notes and lessons learned

2026-10-07: fix is 7f8c27af (GH_TOKEN from the workflow token plus pytest -rs on the Pytest step; zizmor clean). Acceptance is confirmed only by the next CI run's -rs output showing test_real_404_has_its_own_reason as run, not skipped.


## Acceptance

- [x] the card's own pending observation is found: in CI run 37686495589 (v3.8.11) the pytest -rs skip list names lines 108, 116, 130 and 209 of tests/test_memgrep_binary_stale.py and NOT line 185, the real-404 test, with 18094 passed; read with gh run view --log by the main session. Inferred from the skip list, not from a PASSED line.
