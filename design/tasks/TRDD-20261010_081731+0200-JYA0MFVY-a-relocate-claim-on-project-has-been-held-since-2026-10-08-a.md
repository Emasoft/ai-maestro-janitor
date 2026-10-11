---
trdd-id: JYA0MFVY
title: Is the relocate claim on PROJECT held since 2026-10-08 within its expiry bound or was it missed
column: verify_assumptions
status: tasked
created: 2026-10-10T08:17:31+0200
updated: 2026-10-11T02:00:37+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-10T08:17:31+0200
---

# A relocate claim on PROJECT has been held since 2026-10-08 and nothing expired or closed it

Seen 2026-10-10: .janitor/state/memory-maint-claimed-1791460073-1d22bb32.json, intervention relocate, scope PROJECT, stamped 2026-10-08 13:47, still in the claimed pool about 42 hours later; the file carries a report path. expire_stale_claims in scripts/memory_dispatch_claim.py is meant to expire a claim past max(caller floor, the record's own cadence times factor, 6 hours) or close it when a completion report exists. Not read: who calls expire_stale_claims and when, the relocate cadence, and whether the named report exists. TO DO FIRST: read the caller and the record's threshold, check the report file, and say whether this claim is within its bound, should have been closed on its report, or was missed. Acceptance: the claim is closed or expired by the existing path, or the defect that left it is fixed with a test.

## Approval log

- 2026-10-10T08:17:31+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T08:41:41+0200 — column → verify_assumptions. the expiry threshold is unread, so a defect is not established

## Findings

2026-10-11 01:56. ANSWERED, no defect: the claim is WITHIN ITS BOUND. Read by a read-only worker (reports/board/20261011_015620+0200-jya0mfvy-stale-claim.md) and the rule re-read by the main session (scripts/memory_dispatch_claim.py 641 to 660; orphaned_memory_maint.py DEFAULT_FACTOR 3; memory_settings.py relocate_per_day 1): threshold = max(caller floor 0, 24 h cadence times 3 for a non-LOCAL scope, 6 h) = 72 h, so it expires at 2026-10-11 13:47:53 local. The only caller of expire_stale_claims is the heartbeat detector orphaned-memory-maint (line 98, floor 0), which last ran 01:55 today. Its report file is the 276-byte skeleton the claim step writes, with no janitor-outcome marker, so it cannot close early: the agent that claimed it never finished. COST, by design: one abandoned claim defers every relocate marker for 3 days (dispatch.log shows four deferrals). Not changed; a shorter factor for claims is a design choice with no evidence yet that 3 days hurts. CHECK to close this card: after 2026-10-11 13:48, the file memory-maint-claimed-1791460073-1d22bb32.json is gone from .janitor/state and memory-maint-expired-1791460073-1d22bb32.json exists. Not verified: the factor override in the heartbeat environment.
2026-10-11 02:00. REWORDING of the line above (its review, no blocker): expires at 13:47:53 means ELIGIBLE from then, at the next run of the detector; the four deferral lines in dispatch.log are not attributed to this claim; that the agent never finished is inferred from a skeleton report; the caller, its floor and the 01:55 run are the worker reading, not re-read. Not investigated: what happened to the relocate agent of 2026-10-08.
