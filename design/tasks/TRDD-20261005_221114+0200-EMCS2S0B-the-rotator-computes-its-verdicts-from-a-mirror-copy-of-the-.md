---
trdd-id: EMCS2S0B
title: The rotator computes its verdicts from a mirror copy of the login that it cannot verify
column: blocked
status: tasked
created: 2026-10-05T22:11:14+0200
updated: 2026-10-10T15:37:56+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:14+0200
blocked-by: [ZKXQXHBI]
pre-block-column: todo
---

# The rotator computes its verdicts from a mirror copy of the login that it cannot verify

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Every tick of the headless daemon logs that the primary credential is unreadable and that the identity is untrusted, then judges usage and expiry from the mirror copy. All three false verdicts of 2026-10-05 were computed this way. TRDD-A2JLFIQ5 owns only the log wording and TRDD-QQ7QCS3T only the default; this card owns the root question of what the daemon may conclude from an unverified copy.

## Approval log

- 2026-10-05T22:11:14+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Findings

2026-10-10 15:37. MEASURED by the main session, no code. The card's premise is half right. READ (scripts/oauth_rotator/rotator.py, cmd_auto and _resolve_untrusted_live): a headless tick that reads the mirror does not judge from it unverified. It compares the mirror's fingerprint with the session beacon; on a match the mirror is taken as the live credential; when the beacon names another account it probes that account's slot twin; otherwise it stays put and writes a stuck marker. The beacon is restamped only from a session context when the primary item's modification time changes: SessionStart, the Stop hook (throttled) and the heartbeat detector oauth-beacon-refresh. FIELD (rotator.log.1 plus rotator.log, 2026-10-10 09:08 to 15:35): 415 ticks read the mirror; every one took the silent beacon-match branch (0 lines for a different account, 0 for no usable twin, 0 for identity unknowable); 386 ended within limits and 28 exhausted with no target. So the false verdict the card fears was NOT observed in this window. WHAT IS STILL TRUE: the daemon itself cannot verify; between a credential change and the next restamp by a session, mirror and beacon are both old and agree, and the tick judges the previous account (the case TRDD-6AABK2BG narrowed to that gap). Closing the gap needs the daemon to read the primary item, which is built and opt-in and is the owner's decision on TRDD-ZKXQXHBI; this card is BLOCKED on it. The one recorded instance of a verdict for a non-live account is TRDD-LUQKXP3R (todo), which keeps its own investigation. Of the three false verdicts of 2026-10-05 named above, the cap learned from throttle answers (TRDD-YVC3F06V, fixed) does not depend on the mirror; whether the other two do was not traced. NOT MEASURED: the length of the gap in practice; a tick with no janitor session running.
