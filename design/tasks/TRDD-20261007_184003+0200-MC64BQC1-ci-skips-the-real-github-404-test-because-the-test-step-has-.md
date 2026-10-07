---
trdd-id: MC64BQC1
title: CI skips the real GitHub 404 test because the test step has no gh token
column: todo
status: tasked
created: 2026-10-07T18:40:03+0200
updated: 2026-10-07T18:40:03+0200
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
---

# CI skips the real GitHub 404 test because the test step has no gh token

The memgrep-binary-stale test test_real_404_has_its_own_reason calls GitHub for real and skips when gh has no login (559f6102), which is the case on the CI runner. So CI does not check the not-on-GitHub path. Fix: pass the workflow token to the CI Tests step (env GH_TOKEN set to the GITHUB_TOKEN of the run, permission contents read is enough for compare on a public repo), then confirm in the CI log with pytest -rs that the test runs instead of skipping. Found 2026-10-07 after 3.8.8's CI failed on it.

## Approval log

- 2026-10-07T18:40:03+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
