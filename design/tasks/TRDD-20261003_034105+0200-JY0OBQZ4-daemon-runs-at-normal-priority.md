---
trdd-id: JY0OBQZ4
title: Daemon runs at normal priority
column: testing
status: tasked
created: 2026-10-03T03:41:05+0200
updated: 2026-10-05T15:13:53+0200
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
implementation-commits: [30d320eb]
---

# Daemon runs at normal priority

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-03

2026-10-03 remaining before complete: full uv run pytest after R4c lands; host step N2 (owner decision): re-stage this Mac's LaunchAgent at ProcessType Standard, then check plutil -extract ProcessType and ps -o pri; after release, tick wall time under 30 s at high load in daemon.log.

### R1 — normal priority (`scripts/keepalive_install.sh:270`, `oauth_rotator/rotator.py claude_running()`)
1. Change `ProcessType` to `Standard`.
2. Add `timeout=10` to the `ps` call in `claude_running()`.
3. No `taskpolicy` demotion of plugin-update chores: at load 400 it would stop `claude plugin update` from finishing, and that is the path that installs this release.
- **Test**: render the plist through `keepalive_install.sh` into a temp dir and assert `plutil -extract ProcessType raw` ≠ `Background`. Fails before.
- **Verify**: SC.

Parent plan: TRDD-JSQSJ3PZ
2026-10-05 — FIELD CHECK, from a worker's read of the logs, not re-read by the main agent: Field check FAILED: the installed LaunchAgent plist still says ProcessType Background (the N2 re-stage is not done); since the 3.7.0 daemon start (2026-10-04T12:38) 8 of 1313 rotator ticks took 30 s or more, max 168 s (2026-10-05T06:09); the log is only 34 h and load level is not in it. The card stays in testing; the re-stage of the daemon's launch agent at standard priority is a host step for the owner and has not been done.
2026-10-05 — the 'possibly related: TRDD-HVGU9OBL' line above is WITHDRAWN: that card turned out to describe designed behaviour (the headless daemon skips the primary read on purpose and uses the mirror copy), so it is not a cause of this card's symptom.

## Approval log

- 2026-10-03T03:41:05+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-03T06:22:33+0200 — column → testing. code committed; only field acceptance after release remains
2026-10-05 — possibly related: TRDD-HVGU9OBL (the primary live credential was unreadable on every logged rotator tick); a hypothesis, not a finding.
