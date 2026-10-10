---
trdd-id: B78NJU35
title: Spare accounts stop decaying (account B root cause, spare-age alert)
column: testing
status: tasked
created: 2026-10-03T03:41:36+0200
updated: 2026-10-10T03:48:06+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: manager
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-03T03:41:36+0200
project-id: ai-maestro-janitor
review-after: 2026-10-17
parent-trdd: JSQSJ3PZ
blocker-probe: trddgrep --porcelain show JSQSJ3PZ | cut -f3   # probe is VESTIGIAL: this card is NOT blocked (no blocked-by, column testing); parent-trdd JSQSJ3PZ is LINEAGE, not a blocker claim — re-verify the actual chain before treating a release as go-ahead
blocker-holds-if: not-match:^(complete|completed|cancelled|superseded|published|live|failed|live_auditing)$
---

# Spare accounts stop decaying (account B root cause, spare-age alert)

- **R8**: root-cause account B's decay (grant age, refresh cadence, revocation). Keepalive alerts when a spare's last successful refresh is older than N hours.

Parent plan: TRDD-JSQSJ3PZ

## Approval log

- 2026-10-03T03:41:36+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-03T11:22:38+0200 — column → dev. R8 code in progress
- 2026-10-03T11:52:07+0200 — column → testing. code ready; field check after release: daemon.log shows the dead spares probed every 6 h instead of every tick, and one spare-stale alarm
2026-10-09 STAYS in testing (board drain, wave 3): its field case has not been seen: refresh-failed lines about 6 hours apart for a dead spare, and one spare-stale alarm. Both greps return 0 on the current rotator logs, which begin 2026-10-09. review-after 2026-10-17 stands. Assessment: reports/board/20261009_231646+0200-wave3-batchC.md.
2026-10-10 03:48 STAY NOTE RE-CHECKED against rotated logs (board drain; reports/board/20261010_034608+0200-stay-notes-rotated-logs.md; worker-read unless marked). NOTE WRONG: the log line is '[keepalive] <email>: refresh failed (' (rotator.py:3012, read by the main session), not 'refresh-failed'; 0 hits since 2026-10-09T18:25. The spare-stale alarm is never written to a log; it lives in oauth-rotator/active-alerts.json, which holds none now. STILL UNSEEN.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-03

Split-out follow-ups: TRDD-L2CCH9D5 (ticks killed mid-keepalive may spend a refresh grant) and TRDD-JW8CWWNH (rotator log flooded by repeated per-tick lines).
The root-cause cure (TRDD-IT5GEZDZ, outgoing account filed at a switch) is in HEAD only and ships with the next release; until then spares keep dying on every switch.
2026-10-05 — FIELD CHECK, from a worker's read of the logs, not re-read by the main agent: Not observable in daemon.log (0 spare-related lines in 2026-10-04T00:53 to 2026-10-05T11:07): the dead-spare probes and the spare-stale alarm are written to the rotator log and the alert path, not to daemon.log. Check the rotator log for [keepalive] refresh-failed lines about 6 h apart, then close. The card stays in testing; the check could not be made: the rotator log and the alarm record were not read for this card.
