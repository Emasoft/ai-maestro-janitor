---
trdd-id: BUR8AW77
title: Dependency and tool updates wait out a release-age observation period before install
column: human_review
created: 2026-09-24T08:11:55+0200
updated: 2026-10-07T04:44:34+0200
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
status: tasked
implementation-commits: [0ddc41e5]
---

# Dependency and tool updates wait out a release-age observation period before install

owner directive (TRDD-WZKFSQ2N): update to latest "but keeping a observation period delay after new releases to avoid compromised libs or tools being installed". No release-age delay exists anywhere in scripts/ (the only cooldown hits are rate-limit and lock cooldowns). The repo has no .github/dependabot.yml, so Dependabot's `cooldown` option is unused. Scope: Dependabot cooldown for pip/uv, cargo and GitHub Actions; uv's exclude-newer; the same rule for plugin auto-updates, the version-update chore, and the tools the janitor installs. The delay length is an owner decision.

## Approval log

- 2026-09-24T08:11:55+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
OWNER DECISION 2026-09-27 (verbatim, condensed): 'the observation delay for all package installers is a safety rule that must be nudged by the janitor, warning the main claude of package managers that have no safeguards about such early installs. especially 0-days installs must be prevented. but the way the janitor can prevent such things is only by hooks recognizing package installers commands and pre checking if the command to install is installing an early release. but it must be only a warning, not blocking. since there are many exceptions, like libraries developed by the user himself and that it needs to install for testing the deployment. so a OTP code could be the right mechanism to enforce a review and remind the agent of the danger. the hooks for git safety already uses the OTP system, check them out to learn how to implement it.' Shape: a PreToolUse hook recognizing package-installer commands (pip/uv/cargo/npm/yarn/brew...), checking release age of the target version; early/0-day installs get a WARNING (never blocking) with an OTP-confirm escalation path modeled on the existing git-safety hooks; user-authored libraries are the named exception class.
- 2026-09-27T14:47:51+0200 — column → testing by user. owner batch acceptance 2026-09-27 ('complete all TRDDs'); hook landed fd1e39c5 with tests re-verified by main; hooks.json registration is the remaining step and needs the owner's restart consent
REVIEW ROUND 1 CURES (2026-09-27, adversarial fork on fd1e39c5) — (a) knob default verified OFF in source (RELEASE_AGE_HOOK_ALLOW_USER_OVERRIDE, rotator.py:84-86 of the hook): default is warning-only, faithful to the owner's 'warning not blocking'; 'ask' is the opt-in enforce-a-review mechanism. (b) timeout=2.5s is explicit on every urlopen call (hook :122) — fail-hang not possible; hook budget matches the 10s hooks.json cap. (c) 7200-min window is a PROVISIONAL DEFAULT with env override CLAUDE_PLUGIN_OPTION_RELEASE_AGE_OBSERVATION_MINUTES — the owner's number is still pending; this line records the provenance. (d) pyright findings in the test file fixed (ec079567, gate fails closed); test server binds ephemeral port 0. Remaining: hooks.json registration (owner restart consent).
2026-10-04 — 0ddc41e5: test fixture date _NOWISH is now computed at import (UTC minus 10 minutes) so it cannot age out of the 7200-minute window; the nine early-release tests pass again.

## Acceptance

- [x] PreToolUse hook recognizes pip/uv/npm-family/cargo/gem/go installer commands and pre-checks release age (7200-min window)
- [x] early-release finding emits a WARNING and never denies; escalation is permissionDecision "ask" via the git-safety confirm mechanism (grep-verified: zero deny paths)
- [x] local/user-authored installs exempt without lookup (fail-open)
- [x] hooks/hooks.json registration deferred to the owner (needs Claude restart; exact JSON in the worker report)

## Known defects

2026-10-03: tests/test_release_age_guard_hook.py line 33 hard-codes _NOWISH = 2026-09-27T10:00:00Z; since about 2026-10-02 it is outside the 7200-minute window, so 9 early-release tests fail and the release gate is blocked. The hook itself is fine. Fix: _NOWISH = current UTC time minus 10 minutes. Waiting on an owner-approved plain edit (fastedit cannot edit module-level constants); tracked on TRDD-MMUSDJHQ.

## STATE

2026-10-05 — Hook and tests are published in v3.7.0 but the hook is not registered in hooks.json, so it does not run; the registration is development work that can be done now, with the restart needed only to activate it. DECIDED 2026-10-05 (owner delegated decisions): the card returns to todo.
2026-10-05 — correction to the line above: the registration is not simply development work. Registering the hook makes it act on every install, and the card says the 7200-minute window is still provisional. WAITING ON THE OWNER: register the release-age guard hook, and is 7200 minutes the window wanted? The hook file and its tests already ship; unregistered, it does nothing.
2026-10-07: owner decision still open; nothing changed today; the release-age hook stays unregistered and the 7,200-minute window stays provisional.
