---
trdd-id: 7T4J5T6Z
title: The rotator's stuck marker restarts its first-seen time on every tick so the measured duration is always zero
column: todo
status: tasked
created: 2026-10-05T22:08:48+0200
updated: 2026-10-05T22:08:48+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:08:48+0200
---

# The rotator's stuck marker restarts its first-seen time on every tick so the measured duration is always zero

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Observed: a marker read during a stuck episode had first_seen_epoch equal to last_seen_epoch. From reading the code, on a tick that works from the mirror copy the marker is cleared when the beacon fingerprint matches and written again at the end of a still-stuck tick, so first-seen never accumulates. Consequences to verify: the detector that reports 'rotation impossible for N hours' can never reach its hours; the alert reader only tests that the file exists and has no check on the marker's age, so a marker left by a rotator that stopped ticking would alert forever. Also seen: the kind all-accounts-maxed is written for a token that is only close to its expiry.

## Approval log

- 2026-10-05T22:08:48+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
