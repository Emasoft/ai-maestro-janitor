---
trdd-id: I33ST36V
title: drain the board so a release can be published
column: todo
status: tasked
created: 2026-10-05T09:47:28+0200
updated: 2026-10-05T10:12:27+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: infra
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T09:47:28+0200
---

# drain the board so a release can be published

## Why

The project rule blocks a publish while work columns claim activity nobody is doing. Every commit since the last release tag is unpublished, so no host has it; that includes the fixes on TRDD-0QCRG2YX, TRDD-PHS3DIBD and TRDD-3HLI7DMK.

## What blocks a publish today

(1) done on 2026-10-05: TRDD-3HLI7DMK left ai_review for testing after commit 15482026. (2) done on 2026-10-05: the full Python test run passed with no Rust build running. (3) The cards in testing have not been checked for a named live event. (4) TRDD-JSQSJ3PZ and TRDD-K9AHY1ZB sit in dev as parents the linter keeps there; each must say so in its STATE block.
2026-10-05 — item (4) is satisfied: both TRDD-JSQSJ3PZ and TRDD-K9AHY1ZB already say in their STATE blocks that dev means waiting on prerequisite cards. Measured the same day: the last release tag is v3.7.0 and 82 commits sit after it. A rotator alert (account rotation stuck) was live that day; a publish run that meets a rate limit mid-gate is a known failure shape, so the owner is told before a publish starts.

## Tasks

- [x] Commit or drop the TRDD-3HLI7DMK follow-up after its verification and a review of the diff; move that card on.
- [x] Run the owed full Python test run with no Rust build running.
- [ ] For every card in testing, list its named live event from its STATE block; a card with none is a defect to judge one by one, never by a scripted mass change.
- [ ] Confirm the working tree is clean, then publish a patch release through scripts/publish.py (never git push).
- [ ] After CI passes, update the installed plugin; then confirm from the daemon log that the running daemon is on the new version before judging any daemon-side fix; an agent must not signal the daemon.
Daemon fact for the last task: only the OS-spawned keepalive daemon re-stages and exits for respawn when a newer plugin version is cached (scripts/daemon.py, function _keepalive_self_heal); a session-spawned daemon does not replace itself. Which kind runs on a given host was NOT read from its log on 2026-10-05. TRDD-LRGZV19Z (the daemon inherits a session's working directory) suggests a session-spawned one on the host where these fixes were made; that is inferred. If so, the daemon-side fixes of TRDD-0QCRG2YX do not run after a publish until the owner restarts the daemon.

## Order of work adopted on 2026-10-05

Standing process is in the loaded turn-protocol rule, not on this card.

## Do not

See the lessons on the project memory page janitor-fleet-guardian-reachability.
An agent must not mark other projects' findings ledgers as read, and must not signal the daemon.

## Approval log

- 2026-10-05T09:47:28+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
