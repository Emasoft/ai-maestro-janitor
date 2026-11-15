---
trdd-id: G14LKPEC
title: Env dumps Bash guard, live-value matcher and agent-folder sweep for issue 354
column: testing
status: tasked
created: 2026-11-15T23:02:40+0100
updated: 2026-11-15T23:41:00+0100
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
approval-datetime: 2026-11-15T23:02:40+0100
implementation-commits: [a2e5807c, bc1abf68, af9bedf7, 29b8d55f]
---

# Env dumps Bash guard, live-value matcher and agent-folder sweep for issue 354

Issue Emasoft/ai-maestro-janitor#354. Delivers: Bash guard for commands that print a process environment (opt-in hook), shared secret-name test, janitor_env helper, report-only detector env-secret-on-disk (CRED-002). Deferred, owner decisions: in-place redaction, Rust Aho-Corasick, shield needles (blocked on 2V7OAUPE), saved-login needles (rotator freeze), moving pat/cookie/oauth/bearer/key into the shield (Q6LPJTPO), enabling pre_bash_safety by default. Related: Q6LPJTPO 11KWFU5L 119JBB8C 0Y3UW1NF M1218EMH 2V7OAUPE.

## Approval log

- 2026-11-15T23:02:40+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-15T23:19:36+0100 — increment 1 (Bash guard for commands that print a process environment, helper scripts/janitor_env.py, shared secret-name test) committed in a2e5807c; increment 2 (report-only detector env-secret-on-disk, issue code CRED-002) is being applied.
- 2026-11-15T23:26:38+0100 — DECIDED by main-agent@ai-maestro-janitor (owner standing order to decide): env-secret-on-disk ships ON DEMAND only, off the hourly roster. Measured on this repo 2026-11-15: two passes took 49.3 s and 55.2 s; 6 then 3,565 files read, 1,206,764 then 1,203,204 left for the next pass (the agent folders hold about 1.2 million files, 952,625 of them in .trashcan/); no hit in the 3,571 files read, about 0.3 percent of the backlog. Two defects read from env_secrets.sweep(): (1) every file is listed and stat-ed before the time budget starts, so the budget does not bound the pass and a larger tree could pass the 120 s detector kill before the cursor is written (that the walk is most of the 49-55 s is inferred, not timed per phase); (2) files are read oldest change first, so a fresh leak waits behind the backlog. The six roster edits were undone with git restore; they are recoverable only from reports_dev/fanout-apply/scratch/inc2/step10-schedule.patch (gitignored). Follow-up: TRDD-ZANQ1QW0.
- 2026-11-15T23:37:18+0100 — part 2 committed in af9bedf7 (env-secret-on-disk on demand only, CRED-002); bc1abf68 added five cspell words of a2e5807c. A CI-parity preflight on af9bedf7 still failed on cspell (mkfifo) and bandit B108 (env_secrets.py, the /tmp default); fixed in the working tree, not yet committed. Moved to testing.
- 2026-11-15T23:40:59+0100 — the CI fixes are committed in 29b8d55f (supersedes 'not yet committed' in the entry above); the CI-parity preflight on 29b8d55f is PARITY-CLEAN (FAIL=0, WARNING=0, PASS=11).
