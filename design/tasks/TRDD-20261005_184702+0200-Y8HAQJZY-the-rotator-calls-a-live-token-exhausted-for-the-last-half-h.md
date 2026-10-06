---
trdd-id: Y8HAQJZY
title: The rotator calls a live token exhausted for about 24 minutes before its mirror copy is replaced
column: backburner
status: tasked
created: 2026-10-05T18:47:02+0200
updated: 2026-10-06T02:35:06+0200
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

## Findings 2026-10-05

New evidence, read-only (report 20261005_230815 investigate-rotator-stuck-locally-expiring), on the open question whether the copy was current or stale. The rotator log shows 24 ticks from 18:04:00 to 18:27:49 on 2026-10-05 with the live account at 5h=6% 7d=92% marked LOCALLY-EXPIRING and no usable alternate, then the mirror rewritten at 18:28:38 and within limits again. The 30 minute grace was crossed between 18:02:56 and 18:04:00, so the copy expired between 18:32:56 and 18:34:00; the previous episode ended at 10:32:22 after a mirror rewrite, and a lifetime of 8 hours from then gives the same minute. INFERRED from those timings: the copy was current and was replaced about 5 minutes before expiry, so the grace of 30 minutes is about 25 minutes longer than the lead with which the credential is renewed. Not verified: the 8 hour lifetime (taken from project memory), what renews the credential, the expiry value itself. A prediction that tests it without reading a credential: the next episode starts about 02:02 to 02:04 on 2026-10-06 and ends about 02:28 if the same account stays live and no alternate is usable. The installed 3.7.0 does not contain commit 5bdb9521, so the alert still said to capture logins.
Provenance and corrections (review, 2026-10-05): the paragraph above is from a fork's report; the session read the report in full and did not re-run it. Not carried above and NOT explained: the alert line was still printed at heartbeats long after 18:28; one candidate is a stale alert file left in place after the evaluation that failed at 21:33:28 when the process list timed out, not verified. The report proposes a smallest change (in the final stuck branch only, do not mark stuck when the verdict was tripped solely by local expiry on a within-limits answer with a fresh session beacon) and notes that this card already records a rejected wider fix.
2026-10-06, the prediction above tested against the rotator log, read by the session: it HELD in shape and was about four minutes late in time. Predicted: an episode from about 02:02 to 02:04 until about 02:28. Observed: 25 ticks marked LOCALLY-EXPIRING from 01:59:03 to 02:23:38, the mirror rewritten at 02:24:34, within limits again from the next tick; the heartbeat printed the stuck alert on six consecutive fires in that window and stopped by itself, with no login capture. The timing fits a lifetime of 8 hours counted from the previous mirror rewrite at 18:28:38: expiry at 02:28:38, the 30 minute grace crossed at 01:58:38, first marked tick 25 s later, replacement 4 minutes before expiry. The earlier prediction was late because it counted from the 18:32 to 18:34 expiry estimate instead of from the rewrite time. So three episodes in a row (10:08 to 10:32, 18:04 to 18:27, 01:59 to 02:23) show the same thing: the copy is current, the credential is renewed about 4 to 5 minutes before expiry, and the grace of 30 minutes raises a false stuck alert for about 25 minutes once per token lifetime while no alternate is usable. Still not verified: the expiry value itself was never read; what renews the credential; whether the live account stayed the same across the three episodes (account names were not compared).
