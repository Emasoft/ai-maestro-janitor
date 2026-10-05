---
trdd-id: Y8HAQJZY
title: The rotator calls a live token exhausted for the last half hour before Claude Code renews it
column: backburner
status: tasked
created: 2026-10-05T18:47:02+0200
updated: 2026-10-05T18:47:02+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T18:47:02+0200
---

# The rotator calls a live token exhausted for the last half hour before Claude Code renews it

Measured on 2026-10-05 from the rotator log (report in reports_dev, measure-expiring-only): two episodes of 24 ticks each, about eight hours apart, in which every tick logged the live account as exhausted with the reason LOCALLY-EXPIRING while the usage endpoint answered 200 and usage was within limits. Each episode began about one beat after the token copy the tick reads came within EXPIRY_GRACE_H (0.5 h) of its expiresAt, and ended on the tick after the session beacon rewrote the mirror with the newer live credential. In both episodes no safe rotation target existed, so the tick fell through to the stuck branch and wrote the marker of kind all-accounts-maxed; the marker is cleared and re-written on every such tick.

Reading: the pre-expiry trigger fires about 25 minutes before the moment the credential is renewed anyway. With a safe target it causes a swap that was not needed; with none it raises a false stuck alert for about 25 minutes once per token lifetime.

Rejected fix (review, 2026-10-05): staying put when the tick sees 200 within limits and no safe target. The 200 and the expiresAt both belong to the copy the headless daemon reads, not provably to the credential in use, and the change would return before the degraded tier, which is the rescue for a token that is really dying with no session alive to renew it.

Open design question for the owner: should local expiry trip a rotation at all while a session beacon is fresh (a live session renews its own token), and should the grace be shorter than the renewal lead. Related: TRDD-QQ7QCS3T (whether the daemon may read the primary item), TRDD-QHACQPPG, TRDD-JSQSJ3PZ. Not investigated: what renews the token and exactly when; the expiresAt of the mirror was not read (no credential was read for this card).

## Approval log

- 2026-10-05T18:47:02+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
