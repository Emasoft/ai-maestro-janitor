---
trdd-id: K0PMVRN6
title: All three rotator slots died with invalid_grant and rotation stayed put for 17 days
column: todo
created: 2026-09-24T07:32:06+0200
updated: 2026-09-24T08:41:14+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: bugfix
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T07:32:06+0200
relevant-rules: []
labels: [oauth-rotator]
---

# All three rotator slots died with invalid_grant and rotation stayed put for 17 days

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-24
- 2026-09-24 ~08:16: the live item IS readable by /usr/bin/security from a user process: rc=0, 14429-byte JSON, 0.02 s, no dialog (one bounded test, secret discarded). The daemon's 'unreadable' is its own policy skip (JANITOR_ROTATOR_HEADLESS). A re-test after the next rewrite is pending. The fix direction is TRDD-4XND73XD: mirror live→slot, including at the switch.
- Privacy status: this card still contains personal e-mail addresses and account names (owner accepted 2026-09-24; redaction pending the owner's decision).

- 2026-09-24 07:30: all three slots re-captured by hand with `slot_capture_browser.py`: emanuele.sabetta 07:27, ipazia.emasoft (live) 07:28, fmuaddib 07:30. Each OK line named the right account, and each slot is FULL-OAUTH with a refreshToken, expiring in about 8 h. The 07:29:47 tick probed the live account again ("live <the live account> 5h=3% 7d=1% — within limits"), so PROBING is restored. SWITCHING is NOT proven: no switch has happened since.
- NEXT ACTION: verify the rotator switches BEFORE a 429/time-limit wall with no broken continuity (owner 2026-09-24), in and outside the ai-maestro harness; remove the setup-token code path (new card); tell the ai-maestro Claude the ratified procedure.
- Prediction to check (H1): the first account the rotator switches to will log `refresh failed (credential-dead)` about one access-token lifetime (about 8 h) after the switch.
- Stopgap (delegated decision, one time only; not the owner's words): no overnight or unattended recurring captures. One capture of the live account's saved copy at 15:21 on 2026-09-24, run only if the 15:16 renewal evidence is clean. It knowingly deviates from the ratified 'capture the live account last' step, because the alternates are already fresh. Session-only jobs a4d1d3e9 (15:21 capture) and d463edea (09:41 keepalive check), disabled with CronDelete <id>; both die if the session restarts. Log line: interim-capture: <email> captured|skipped(<reason>). Update this bullet with the result.

## Symptom (owner, 2026-09-24)

"i had to manually rotate again. why?" rotator.log (retained from 02:01) shows the same pattern every tick:
- `primary live credential UNREADABLE from this context — using the -livebak MIRROR` (TRDD-7PYTX4E9 F1)
- `live account <x> has no usable slot twin to probe — staying put this tick (fail-safe)`
- `[keepalive] <every account>: refresh failed (credential-dead)`, meaning 400/401 invalid_grant (`REFRESH_FAIL_CREDENTIAL_DEAD`, rotator.py)
- `cascade: reauth-nudge=...`, later `renew-cookie=...`

`rotator.py list` before the re-capture: fmuaddib and ipazia slots captured 2026-08-26, access tokens expired about 420 h and 406 h earlier (around 2026-09-06/07). Rotation had been dead for about 17 days, not one night.

## Hypotheses (none verified)

- H1, a slot spent by the live refresh (leading). When the rotator switches to an account, it installs that slot's grant as the live credential. Claude Code then refreshes it, which rotates and spends the refresh token the slot still holds. The write-back of the refreshed live credential into the slot (the capture step) cannot run, because the daemon cannot read the live keychain item (F1: "primary live item present but unreadable from this context"). The slot then dies with invalid_grant at its next keepalive. Likely related: TRDD-V5RXQ4NB (the app resets the credentials item partition list on every token refresh). The durable fix would be F1 or write-back, not re-capture.
- H2, idle expiry after the TLS outage. TRDD-X6I04SAO: since about 2026-09-02, the daemon Python had no CA bundle, so every refresh failed as a network error. If refresh tokens have a maximum idle lifetime, days of failed refreshes would end in invalid_grant.
- H3, a new grant evicting older ones. Minting a new grant (a capture, or a manual `/login`) may revoke the account's older refresh tokens server-side. That would also kill the live session's token after a capture on the live account. Test: does this session hit a login prompt within about 8 h of the 07:28 ipazia capture?

## How to tell them apart

- daemon.log and rotator.log history 2026-09-02 to 2026-09-10 (whatever is retained, including rotated or backup copies): the KIND of each keepalive failure (network or credential-dead) per account, and when it switched. A switch from network to credential-dead with no switch in between supports H2. credential-dead right after the account went live supports H1.
- Whether any code path writes the refreshed live credential back into its slot, and what the F1 read failure actually is (security exit code, ACL/partition list).

## Also found

- `oauth-login-needed` reached the owner on the heartbeat only after they had already rotated by hand.
- Auto-bootstrap (the RENEW_COOKIE actor) is opt-in via CLAUDE_ROTATOR_AUTO_BOOTSTRAP (default off, TRDD-5OJX3SCF). So after `open-login.sh`, nothing converts the saved session into a slot unless a human runs the capture. The janitor-refresh-cc-logins skill instead tells the owner to mint setup-tokens manually, citing the 2026-09-09 ruling. The owner reports the 1-year setup-token keys "are not working", and TRDD-BMITQ2MN's ai-maestro half is still open. The browser capture worked on 2026-08-07 and again on 2026-09-24, so the skill's premise that "a driven browser does not clear" the consent page is contradicted for this flow. Owner decision needed.

## Approval log

- 2026-09-24T07:32:06+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-24 — identity correction: issuer fields changed from the host username (a trddgrep default) to the session id; original in git history.
- 2026-09-24 — privacy status: this card still contains personal e-mail addresses and account names (owner accepted the commit 2026-09-24; redaction pending the owner's decision). publish.py's G1b address lint is expected to refuse a release until they are redacted; the correction above changed only the issuer fields and the MANDATE line's issuer.

## Owner decisions 2026-09-24 (verbatim)

> no need, now it is ok. but remember: the long lived tokens are not working, so you can remove that code. the current method you just used is the right one, so save it in memory. but still you must check that the rotation will actually happen in time, just before the api/time-limit error appear. otherwise continuity is broken. you must ensure rotate is executed without broken continuity of the agents jobs across all claude code, in or outside of the ai-maestro harness. i suggest to message the ai-maestro claude to inform it of the right procedures to rotate and renew you just used.
Context: "no need, now it is ok" answered the question whether to amend commit 3185baac to remove private data from TRDD-K0PMVRN6. The owner said no amend is needed.
> why only the server can read the keychain? the janitor daemon must read it too. not to mention that the keychain stored oauth of the user accounts must all be shared between the ai-maestro server daemon (the janitor daemon equivalent that replaces it when the server is running) and the janitor daemon.

