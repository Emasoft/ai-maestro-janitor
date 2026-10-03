---
trdd-id: JY0OBQZ4
title: Daemon runs at normal priority
column: todo
status: tasked
created: 2026-10-03T03:41:05+0200
updated: 2026-10-03T03:43:03+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: manager
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-03T03:41:05+0200
project-id: ai-maestro-janitor
parent-trdd: JSQSJ3PZ
derived: true
---

# Daemon runs at normal priority

### R1 — normal priority (`scripts/keepalive_install.sh:270`, `oauth_rotator/rotator.py claude_running()`)
1. Change `ProcessType` to `Standard`.
2. Add `timeout=10` to the `ps` call in `claude_running()`.
3. No `taskpolicy` demotion of plugin-update chores: at load 400 it would stop `claude plugin update` from finishing, and that is the path that installs this release.
- **Test**: render the plist through `keepalive_install.sh` into a temp dir and assert `plutil -extract ProcessType raw` ≠ `Background`. Fails before.
- **Verify**: SC.

Parent plan: TRDD-JSQSJ3PZ

## Approval log

- 2026-10-03T03:41:05+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
