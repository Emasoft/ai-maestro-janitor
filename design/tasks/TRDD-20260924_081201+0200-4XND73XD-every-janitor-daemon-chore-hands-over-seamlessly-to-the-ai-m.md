---
trdd-id: 4XND73XD
title: Every janitor daemon chore hands over seamlessly to the ai-maestro server when it is online and back when it is not (janitor side)
column: todo
created: 2026-09-24T08:12:01+0200
updated: 2026-09-24T08:12:01+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: feature
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T08:12:01+0200
---

# Every janitor daemon chore hands over seamlessly to the ai-maestro server when it is online and back when it is not (janitor side)

## Owner ruling 2026-09-24 (verbatim)

> the ai-maestro server is responsibility of the ai-maestro claude. you must help him to make the janitor work seamlessly in and outside of the harness, passing down the rotation task (and all janitor daemon tasks) to the ai-maestro server when it is online. but only collaborating together you can ensure that the janitor works in every case, within or without the ai-maestro harness.

Then: the joint protocol (M1-M8) was agreed with the ai-maestro Claude on 2026-09-24. The spec will live on the ai-maestro side (path to be added when it exists). Janitor-side items:
(a) instance_is_server_owned (scripts/lib/harness_backend.py:626-629) requires a live server lease, not just the aimaestro CLI; today the ESC/wake passes skip harness agents while the server is down;
(b) rotate_to.py takes the shared lock and respects the lease;
(c) read and renew the per-chore ownership lease; stand down and take over for every GLOBAL_CHORE;
(d) honour refresh_dead_fp;
(e) read one shared threshold table;
(f) an immediate tick on the retry-wedge signal.
M1 is conditional on a flock(2) interop test between Python fcntl.flock and /usr/bin/lockf. Known limit in fallback mode: the headless daemon cannot read the primary live item, so it cannot mirror live→slot, and slots decay after each switch; that needs its own mitigation (browser re-capture). Related: TRDD-K0PMVRN6, TRDD-6CRC9SQQ, TRDD-HXZ8B0IS.

## Approval log

- 2026-09-24T08:12:01+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
