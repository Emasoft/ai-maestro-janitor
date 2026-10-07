---
trdd-id: 3OS6AXV3
title: Owner warned out of band when no rotation target exists or the rotator stalls
column: human_review
status: tasked
created: 2026-10-03T03:41:23+0200
updated: 2026-10-07T04:30:22+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: manager
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-03T03:41:23+0200
project-id: ai-maestro-janitor
parent-trdd: JSQSJ3PZ
derived: true
implementation-commits: [b4ba693b, b956914d, 2732ae2c, 95422abd]
---

# Owner warned out of band when no rotation target exists or the rotator stalls

### R4 — out-of-band warning (daemon side, builds on TK529Q0F `rotation-stuck.json`)
1. **Conditions:**
   - (a) **No rotation target**: no slot has a future expiry and no refresh succeeded. Fires once, then hourly.
   - (b) **Live token past expiry and not refreshed** for 5 minutes.
   - (c) **No completed tick** for 10 minutes.
   - (d) **`rotation-stuck.json` exists.**
2. **Channel**: a macOS notification from the daemon. Reuse an existing notifier if `grep -rn "display notification" scripts` finds one; otherwise use `osascript -e 'display notification …'`.
   - It is not a heartbeat drift line, because after expiry every model turn is "Login expired".
   - Also write `rotator-alert.json`, which the heartbeat surfaces when a turn can run.
   - The text names the one action (for example "run /janitor-capture-all-logins") and never includes a token.
3. **Ordering**: the dispatch phase that surfaces `rotator-alert.json` runs **before** the summary-hold gate.
- **Test**: real temp state for each condition; assert the notifier argv and the debounce. Fails before.
- **Verify**: SC.

Parent plan: TRDD-JSQSJ3PZ

## Approval log

- 2026-10-03T03:41:23+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-03T06:22:36+0200 — column → dev. R4c in progress (live account excluded from no-rotation-target; auth-failed condition from the StopFailure hook)
- 2026-10-03T13:53:58+0200 — column → testing by main-agent@ai-maestro-janitor. implementation landed
- 2026-10-03 — R4 cannot reach complete until the owner approves a one-off plain edit for the fastedit-refused R4b leftovers (dead _ACTIONS entry, LIVE_EXPIRED_GRACE_S, DEBOUNCE_S comment, 'add a spare account' alert wording), listed on TRDD-MMUSDJHQ.
2026-10-04 — 95422abd removed LIVE_EXPIRED_GRACE_S and the live-token-expired action text. Body condition (b) 'live token past expiry and not refreshed for 5 minutes' is NOT implemented: the code comment in scripts/lib/rotator_alert.py (above the tick-stalled check) says no such condition exists on purpose. The card body still lists (b); whether (b) is dropped for good is an open decision, so this card stays in testing. Still open: alert wording and the DEBOUNCE_S comment.
2026-10-05 — DECIDED (owner delegated decisions; the owner may reverse it): body condition (b), live token past expiry and not refreshed for five minutes, is DROPPED, not satisfied. Reason: the only expiry reading available for the live account is stale by design and would fire about eight hours after every switch; the wall it meant to catch is reported by the auth-failed marker. Reopen if a reliable expiry source appears. The line above saying the alert wording and a comment are still open is superseded: both were fixed in a71a5ac5. OBSERVED 2026-10-05, not a pass: the line 'rotator alert: account rotation is stuck' appeared in a session's heartbeat output on several fires; which condition raised it was not read. RESUME POINT. Column testing. NAMED LIVE EVENT: that alert is traced once to the condition that raised it, in the rotator alert state file, and matches condition (a), (c) or (d).
2026-10-05 — the status line above was appended here by mistake; the card's STATE section now holds the current one.

## STATE

2026-10-05 — DECIDED (owner delegated decisions; the owner may reverse it): body condition (b) is DROPPED, not satisfied; reason, per a worker's reading of the code comment at the alert module: the only expiry reading for the live account is stale by design; reopen if a reliable source appears. The alert 'account rotation is stuck' was live on 2026-10-05; read from the alert state on that day: condition key rotation-stuck, first seen 2026-10-05 (read from the recent-alert debounce file; the live alert file was absent at read time, so it is not raised at this moment). That is condition (d) of this card, observed live. RESUME POINT: Column testing. The alert was observed for one condition; nothing waits on an event except the owner clearing it with the capture-all-logins command.
2026-10-05 — correction: 'observed live' above is too strong. The read came from the recent-alert record, which shows the rotation-stuck condition was raised at some point on 2026-10-05; the live alert file was absent, and the heartbeat stopped printing the alert after about 10:29 that day, so it may have cleared by itself. WAITING ON THE OWNER, not on an event: if the alert returns, the capture-all-logins command is the owner's action.
2026-10-05 — possibly related: TRDD-HVGU9OBL (the primary live credential was unreadable on every logged rotator tick); a hypothesis, not a finding.
2026-10-05 — the rotation-stuck alert was printed again by the heartbeat later the same day, so it had not cleared for good. If TRDD-HVGU9OBL turns out to be its cause, capturing logins may not be the remedy; read that card before acting on the alert.
2026-10-05 — the 'possibly related: TRDD-HVGU9OBL' line above is WITHDRAWN: that card turned out to describe designed behaviour (the headless daemon skips the primary read on purpose and uses the mirror copy), so it is not a cause of this card's symptom.
2026-10-05 — for the owner's action on the rotation-stuck alert, read in the code by a worker: capturing logins does not change the daemon's primary read; it can help when a spare account's stored login is unusable or an identity cannot be established, and does nothing when every account is simply at its usage limit.
2026-10-07: the owner question 'allow a one-off plain edit for the R4b leftovers' is moot: the leftovers landed in 95422abd and a71a5ac5, and the owner ruled 'Allow plain edits for this job' on 2026-10-06 (card FQVEILVK). Remaining owner item: condition (b) was dropped by delegated decision on 2026-10-05; the owner may reverse it.
