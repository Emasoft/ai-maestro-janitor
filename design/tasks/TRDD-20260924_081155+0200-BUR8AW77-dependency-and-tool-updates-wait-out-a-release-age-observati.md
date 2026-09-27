---
trdd-id: BUR8AW77
title: Dependency and tool updates wait out a release-age observation period before install
column: todo
created: 2026-09-24T08:11:55+0200
updated: 2026-09-27T13:51:58+0200
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
OWNER DECISION 2026-09-27 (verbatim, condensed): 'the observation delay for all package installers is a safety rule that must be nudged by the janitor, warning the main claude of package managers that have no safeguards about such early installs. especially 0-days installs must be prevented. but the way the janitor can prevent such things is only by hooks recognizing package installers commands and pre checking if the command to install is installing an early release. but it must be only a warning, not blocking. since there are many exceptions, like libraries developed by the user himself and that it needs to install for testing the deployment. so a OTP code could be the right mechanism to enforce a review and remind the agent of the danger. the hooks for git safety already uses the OTP system, check them out to learn how to implement it.' Shape: a PreToolUse hook recognizing package-installer commands (pip/uv/cargo/npm/yarn/brew...), checking release age of the target version; early/0-day installs get a WARNING (never blocking) with an OTP-confirm escalation path modeled on the existing git-safety hooks; user-authored libraries are the named exception class.
