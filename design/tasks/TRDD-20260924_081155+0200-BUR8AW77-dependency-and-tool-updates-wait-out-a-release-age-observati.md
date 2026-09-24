---
trdd-id: BUR8AW77
title: Dependency and tool updates wait out a release-age observation period before install
column: todo
created: 2026-09-24T08:11:55+0200
updated: 2026-09-24T08:11:55+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: feature
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T08:11:55+0200
---

# Dependency and tool updates wait out a release-age observation period before install

owner directive (TRDD-WZKFSQ2N): update to latest "but keeping a observation period delay after new releases to avoid compromised libs or tools being installed". No release-age delay exists anywhere in scripts/ (the only cooldown hits are rate-limit and lock cooldowns). The repo has no .github/dependabot.yml, so Dependabot's `cooldown` option is unused. Scope: Dependabot cooldown for pip/uv, cargo and GitHub Actions; uv's exclude-newer; the same rule for plugin auto-updates, the version-update chore, and the tools the janitor installs. The delay length is an owner decision.

## Approval log

- 2026-09-24T08:11:55+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
