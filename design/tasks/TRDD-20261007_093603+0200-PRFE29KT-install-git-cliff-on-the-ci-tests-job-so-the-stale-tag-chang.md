---
trdd-id: PRFE29KT
title: Install git-cliff on the CI Tests job so the stale-tag changelog tests run there
column: testing
status: tasked
created: 2026-10-07T09:36:03+0200
updated: 2026-10-10T22:30:49+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: infra
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T09:36:03+0200
---

# Install git-cliff on the CI Tests job so the stale-tag changelog tests run there

556b78be skips two tests (the TNNII9S8 stale-tag changelog tests) where git-cliff is absent. Add an install step for git-cliff to the CI Tests job, pinned per the workflow rules (an action pinned to a commit SHA, or a pinned release), so those tests run on the runner again.

## Approval log

- 2026-10-07T09:36:03+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T22:30:49+0200 — column → testing by main-agent@ai-maestro-janitor. built; proof is the next CI run

## Findings

2026-10-10 22:30 BUILT: .github/workflows/ci.yml, Tests job, a step 'Install git-cliff (pinned)' after 'Set up Python': uv tool install git-cliff==2.14.2, then the uv tool bin dir appended to GITHUB_PATH. 2.14.2 is the version on the dev host, and it installs from PyPI (uvx --from git-cliff==2.14.2 git-cliff --version printed 2.14.2). No third-party action was added, so there is nothing to pin to a commit. CHECKED locally: the file parses and the Tests job's steps are in the intended order; actionlint passes; zizmor (offline mode) reports no findings; tests/test_publish_stale_tag_recovery.py 16 passed; the four test files that read ci.yml pass. NOT CHECKED, cannot be before a push: that the step works on the ubuntu runner and that the two git-cliff tests then run instead of skipping (the -rs flag of the Pytest step prints skips, so the CI log of the next release shows it).

## Acceptance

- [x] The Tests job installs git-cliff at a pinned version.
- [ ] FIELD, next release: the CI Tests log shows the two stale-tag changelog tests ran (not in the skip summary).
