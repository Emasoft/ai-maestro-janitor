---
trdd-id: EMCS2S0B
title: The rotator computes its verdicts from a mirror copy of the login that it cannot verify
column: blocked
status: tasked
created: 2026-10-05T22:11:14+0200
updated: 2026-10-10T20:10:18+0200
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
blocker-probe: trddgrep --design-dir "$(git rev-parse --show-toplevel)/design" show ZKXQXHBI --porcelain | cut -f3
blocker-holds-if: not-match:^(complete|completed|cancelled|superseded|published|live|failed|live_auditing)$
---

# The rotator computes its verdicts from a mirror copy of the login that it cannot verify

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Every tick of the headless daemon logs that the primary credential is unreadable and that the identity is untrusted, then judges usage and expiry from the mirror copy. All three false verdicts of 2026-10-05 were computed this way. TRDD-A2JLFIQ5 owns only the log wording and TRDD-QQ7QCS3T only the default; this card owns the root question of what the daemon may conclude from an unverified copy.

## Approval log

- 2026-10-05T22:11:14+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Findings

2026-10-10 15:37. MEASURED by the main session, no code. The card's premise is half right. READ (scripts/oauth_rotator/rotator.py, cmd_auto and _resolve_untrusted_live): a headless tick that reads the mirror does not judge from it unverified. It compares the mirror's fingerprint with the session beacon; on a match the mirror is taken as the live credential; when the beacon names another account it probes that account's slot twin; otherwise it stays put and writes a stuck marker. The beacon is restamped only from a session context when the primary item's modification time changes: SessionStart, the Stop hook (throttled) and the heartbeat detector oauth-beacon-refresh. FIELD (rotator.log.1 plus rotator.log, 2026-10-10 09:08 to 15:35): 415 ticks read the mirror; every one took the silent beacon-match branch (0 lines for a different account, 0 for no usable twin, 0 for identity unknowable); 386 ended within limits and 28 exhausted with no target. So the false verdict the card fears was NOT observed in this window. WHAT IS STILL TRUE: the daemon itself cannot verify; between a credential change and the next restamp by a session, mirror and beacon are both old and agree, and the tick judges the previous account (the case TRDD-6AABK2BG narrowed to that gap). Closing the gap needs the daemon to read the primary item, which is built and opt-in and is the owner's decision on TRDD-ZKXQXHBI; this card is BLOCKED on it. The one recorded instance of a verdict for a non-live account is TRDD-LUQKXP3R (todo), which keeps its own investigation. Of the three false verdicts of 2026-10-05 named above, the cap learned from throttle answers (TRDD-YVC3F06V, fixed) does not depend on the mirror; whether the other two do was not traced. NOT MEASURED: the length of the gap in practice; a tick with no janitor session running.
2026-10-10 15:42, corrections after the review of e2b1b396 and four further checks. (1) BASIS of 'all took the beacon-match branch', which the match branch itself never logs: every other exit of _resolve_untrusted_live writes a line (different account, no usable twin, identity unknowable; 0 of each), cmd_auto returns silently when it gets nothing back, and each of the 415 mirror lines is followed by a verdict line before the next one (386 within limits, 28 exhausted counted on the directly following line, one more reached after an intervening line). So it is an inference from the code order, not an observed line. (2) The 415 count is complete: no release tag contains the commit that reworded the line (0449b637), so the installed rotator still writes the old wording that was counted. (3) 'Restamped only from a session context' needs one more caller: cmd_tick calls the stamp on every tick, and in the headless daemon that call writes nothing because the primary read is skipped by policy; the command form used by SessionStart and by the heartbeat detector is the other caller (both read by the main session). (4) WITHDRAWN: 'the false verdict the card fears was NOT observed in this window'. The 28 exhausted verdicts (13:33 to 13:57) each rest on the mirror copy's own local expiry (the line says 5h=13% 7d=75% +LOCALLY-EXPIRING); whether the credential in use had been renewed by then and the mirror simply not restamped was not checked, so those 28 are verdicts of unknown truth, not shown true and not shown false. That is the nearest thing to this card's own failure case in the window and it is the first thing to check when the card is worked. (5) Of the three false verdicts of 2026-10-05, each has an owner card (TRDD-YVC3F06V fixed; TRDD-QHACQPPG; TRDD-LUQKXP3R); none is shown to be caused by the mirror and not by reading a usage-endpoint 429 as a limit. (6) The review's point that blocked parks an agent-workable half is ACCEPTED in part: item (4) is workable without the owner; the card stays blocked on TRDD-ZKXQXHBI for its fix and item (4) is named here so it is not lost.
