---
trdd-id: MA3E3VA9
title: A janitor clear fires on a session that is waiting for its owner's answers
column: complete
status: archived
created: 2026-10-05T22:11:18+0200
updated: 2026-10-10T17:04:02+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:18+0200
release-via: none
---

# A janitor clear fires on a session that is waiting for its owner's answers

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

On 2026-10-05 a clear fired on a session that had asked the owner five questions and was waiting, and on another with a very large context. Decide whether waiting on the owner should hold a clear, and how the questions survive it.

## Approval log

- 2026-10-05T22:11:18+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T17:04:02+0200 — COMPLETE by main-agent@ai-maestro-janitor. archived → complete.

## Corrections

2026-10-05 (review): the first clear is known only from the handoff text and the count of questions from the earlier session's own summary; the second clear was on another project and was not shown to be waiting on its owner.
2026-10-10 17:04. DECIDED, no code (wave 14 card 3). READ: scripts/lib/external_clear.py refuses a clear with why=awaiting-user when the transcript tail ends on an unanswered human-facing tool call (ExitPlanMode or AskUserQuestion; scripts/lib/fleet_scan.py awaiting_user_decision), since fde1bf40 of 2026-08-14, in tags from v3.3.0. So a question asked through the question tool already holds a clear. Questions written as prose at the end of a reply do not: the turn has ended and nothing in the transcript marks it as waiting. DECISION: prose questions do NOT hold a clear. Reasons: (1) the automatic clear needs the human idle for an hour or the prompt cache certainly expired, at which point the next owner message re-bills the whole context whether or not the questions are held; (2) telling a prose question from an ordinary closing sentence needs a judgement no pure predicate can make, and a wrong hold blocks every clear; (3) the questions survive: the cleared session's read-first copy holds the last replies verbatim (this session read its copy whole after the clear of 16:35 and it carried the previous replies in full, including the open owner item). How the questions survive is therefore the continuity block's job, owned by TRDD-DS3WDTPV and TRDD-D7RLXAN1 (both testing). NOT CHECKED: the 2026-10-05 clear itself (known only from the handoff text, per the correction above); this project's external-clear.log holds 0 awaiting-user lines, so the veto is unobserved here and rests on its tests; a forced clear (--force) was not read for whether it honours the veto, though the comment at scripts/external_handoff_clear.py line 482 says every safety veto still applies. FIELD CASE UNOBSERVED.

## Acceptance

- [x] Decided whether waiting on the owner holds a clear: a question-tool call does (built before this card, v3.3.0); prose questions do not, by decision, and survive through the read-first copy. NARROWED: no code; the 2026-10-05 event was not reproduced.
