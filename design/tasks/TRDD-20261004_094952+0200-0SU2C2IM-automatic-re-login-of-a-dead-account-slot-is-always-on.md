---
trdd-id: 0SU2C2IM
title: Automatic re-login of a dead account slot is always on
column: testing
status: tasked
created: 2026-10-04T09:49:52+0200
updated: 2026-10-04T20:13:09+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-04T09:49:52+0200
parent-trdd: JSQSJ3PZ
implementation-commits: [90135636, 94bf446d, e0c9cabe, 3cb92e46, 7598cb5c, 3b96c091, 8f37dee1, 60dd828d, c91af837]
---

# Automatic re-login of a dead account slot is always on

OWNER DECISION 2026-10-04, verbatim: "never stop the automatic relogin". Asked in the same conversation: "do you want the background service to open Chrome and re-capture a dead login on its own?"

Context. On the night of 2026-10-04 two spare account slots were credential-dead (refresh refused) while each account's claude.ai web session cookie was valid until 2026-10-22. The rotator logged `cascade: renew-cookie=...` on every tick and did nothing: `_bootstrap_seeded_slots` in scripts/oauth_rotator/rotator.py only launches `slot_capture_browser.py` when the daemon environment has CLAUDE_ROTATOR_AUTO_BOOTSTRAP truthy, and it defaults to OFF (card 5OJX3SCF, "surprise headful Chrome"). The owner rotated by hand. Evidence: reports/oauth-rotator/20261004_094111+0200-cookie-leg-recon.md and reports/oauth-rotator/20261004_092844+0200-rotation-failure-1004-recon.md.

Requirement. The automatic re-login (cookie leg) runs by default in the daemon tick whenever a slot is eligible. It must not depend on an environment variable being set by hand.

Open points to settle in design, not decided by the owner's sentence: (1) whether an explicit CLAUDE_ROTATOR_AUTO_BOOTSTRAP=0 stays as an emergency off switch; (2) the per-slot launch cap ROTATOR_MAX_BOOTSTRAP_LAUNCHES (3) also stops re-login after three tries, so decide whether it resets on a time basis; (3) a headful Chrome opening unattended (locked screen, Cloudflare) is unverified; (4) capturing the LIVE account mints a new grant and may evict the running session's own grant, so the live account stays excluded; (5) skills/janitor-refresh-cc-logins/SKILL.md step 4 and memory atom ATOM-LTOX-A05P say auto-bootstrap is opt-in and must be updated.

Verify. With a credential-dead spare slot and a valid web session cookie, one daemon tick with NO environment variable set logs an `auto-bootstrap:` launch line and the slot is re-filed; a test asserts the default.

Related: supersedes the default chosen in TRDD-5OJX3SCF; parent umbrella TRDD-JSQSJ3PZ.

## Approval log

- 2026-10-04T09:49:52+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-04 — OWNER, verbatim, second directive: "don't make temporary things. implement permanent solutions." Consequence: the default is changed in code (scripts/oauth_rotator/rotator.py, _bootstrap_seeded_slots); a launchctl setenv made the same day is temporary and is not the fix.
- 2026-10-04 — CORRECTION to Context: all three slot tokens were expired and refresh-refused that night, not two; the cascade line lists two because the live account is always classed healthy. The cause (flag off) is strongly inferred, not proven. That the web session cookie suffices was shown on 2026-10-04 for one spare account by a manual capture; the other spare profile was signed in to the wrong account, so an unattended capture would have filed the wrong slot (janitor issue 179).
- 2026-10-04 — DESIGN DECISION for this card: unset or empty variable means ON; an explicit falsy value (0, false, no, off) stays as an emergency stop. The owner did not ask to remove the stop or the three-launch cap; both stay until the owner says otherwise.
- 2026-10-04 — KNOWN LIMIT: the re-login cannot help a daemon that cannot read the keychain. On 2026-10-04 09:03 the daemon lost keychain access after the macOS login session was replaced; see the sibling card created the same day.
- 2026-10-04T20:10:59+0200 — column → testing. Code landed (default ON, refusal refund and alert in c91af837); nobody is writing code for it. Awaiting end-to-end observation on this machine after 3.7.1 is installed; open items stay listed on the card.

## Open items carried past the first release (2026-10-04)

A refused capture (profile signed in to another account) uses up one of the three per-slot launches and raises no alert; the owner sees nothing. Fix: a refusal must not count as a launch and must raise the out-of-band alert naming the profile and the account it is signed in to.
The three-launch cap never resets, which contradicts the owner's 'never stop the automatic relogin'. Awaiting the owner's decision; proposed: reset every 24 hours and alert each time the cap is exhausted.
The capture guard's 30-second page-read timer is not reset on a poll where the Authorize button is absent, so a later single failed read can refuse early (review of 7598cb5c). Rare; not fixed.
Not yet observed end to end on this machine: no automatic re-login, no renewal of a spare, and no account switch has been seen running the new code. The temporary launchctl setting of CLAUDE_ROTATOR_AUTO_BOOTSTRAP must be removed after the release is installed, so the code default is what runs.
The live account's slot is never re-captured automatically (by design, e0c9cabe/3cb92e46); it depends on the session-written copy of the live login, which has not been observed working on this machine.
Memory page oauth-rotation-renew-reauth-operations still says auto-bootstrap is opt-in and default OFF (its step-3 sentence, the description and keywords of ATOM-LTOX-A05P, and lesson ATOM-DTL6-3KUL). A first correction in 8f37dee1 attached superseding lessons to the wrong atoms and was reverted in 60dd828d. Needs a correction pass that matches atom ids to bodies first, supersedes only the opt-in statements, and keeps the Verify step valid.
2026-10-04 — Item 1 (a refused capture uses up a launch and raises no alert) is implemented in c91af837: the capture leaves a marker, the launcher refunds the attempt once and holds relaunches for six hours, and the alert names both accounts. Follow-ups in progress: clear the marker on a successful capture, refund only a charged launch, carry the account as data instead of parsing the message.
2026-10-04 column testing (was dev). Correction to the move reason - c91af837 is NOT inside the 3.7.0 release (git merge-base against tag v3.7.0), so the refusal refund and alert first ship in 3.7.1. Of the three follow-ups listed above as in progress, two landed in cbb431b5 (the marker clears on a good capture, only a charged launch is refunded). The third, carrying the account as data instead of parsing the message, has no commit and no card. Still waiting on the owner - whether the three-launch cap resets (proposed every 24 hours). Still stale - memory page oauth-rotation-renew-reauth-operations says auto-bootstrap is opt-in. NEXT ACTION - after 3.7.1 is installed, observe one automatic re-login with no environment variable set.
