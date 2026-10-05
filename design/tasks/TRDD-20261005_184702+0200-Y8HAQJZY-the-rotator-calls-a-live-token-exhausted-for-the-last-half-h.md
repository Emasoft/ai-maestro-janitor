---
trdd-id: Y8HAQJZY
title: The rotator calls a live token exhausted for about 24 minutes before its mirror copy is replaced
column: backburner
status: tasked
created: 2026-10-05T18:47:02+0200
updated: 2026-10-05T18:47:59+0200
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

## Corrections

2026-10-05 (review of this card): what renews the credential was NOT investigated, so the earlier title and the words 'renewed anyway', 'newer', 'once per token lifetime' and 'a swap that was not needed' are inferences, not measurements. Measured: two episodes, 10:08:15 to 10:32:22 and 18:04:00 to 18:27:49, 24 ticks each; each ended on the tick after a log line saying the beacon updated the mirror to the live credential, and the fingerprint prefix in that line differed between the two episodes. Two readings stay open and imply different fixes: (1) the mirror was current and the real token was replaced shortly before its expiry, so the trigger is early but true; (2) the mirror was stale and the real token had been replaced earlier, so the trigger is false. What would separate them: the expiresAt of the mirror against the time of the beacon rewrite, or a tick that can read the primary item during an episode. That an episode begins when the copy comes within the grace is consistent with the timing, not measured. The marker being cleared and re-written each tick is from reading the code (clear when the beacon fingerprint matches the mirror, re-mark at the end of a still-stuck tick), not observed on disk. The test test_cmd_auto_proactive_swap_on_locally_expiring_live pins the pre-expiry swap as intended behaviour, so changing it is a design change, not a bug fix.
