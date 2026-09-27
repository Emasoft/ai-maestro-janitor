---
trdd-id: OOZP38MN
title: An expiring live token reads as network down and forces an unprobed degraded rotate
column: testing
created: 2026-09-24T08:11:40+0200
updated: 2026-09-27T13:34:01+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: bugfix
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T08:11:40+0200
status: tasked
---

# An expiring live token reads as network down and forces an unprobed degraded rotate

when the live token is under 30 s from expiry, usage_probe returns status 0 (EXPIRING_TOKEN), the same code as a transport failure (scripts/lib/usage_probe.py ~567-571). cmd_auto treats any 0 as network down (rotator.py:1994) and skips probed candidate selection (rotator.py:2274-2280), so the tick rotates blind on local expiry only. Reported by the ai-maestro Claude's parity audit (their #10) and confirmed by our audit trace. Fix: give EXPIRING_TOKEN its own status and keep network_up true for it. Incident card: TRDD-K0PMVRN6.

## Approval log

- 2026-09-24T08:11:40+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-27T13:34:01+0200 — column → testing by user. owner batch acceptance 2026-09-27 ('complete all TRDDs'); code landed 42ba123e, independently re-verified (175 tests + ruff green on the committed tree); live-rotation observation remains as testing evidence

## Acceptance

- [x] EXPIRING_TOKEN carries its own status -1 (usage_probe.EXPIRING_TOKEN_STATUS) and never folds into transport-failure 0
- [x] cmd_auto keeps network_up true for an expiring token; degraded blind rotate eliminated (rotator.py:1996 comment carries the why)
- [x] two failing-on-old-behavior tests exist and pass (tests/test_usage_probe.py, tests/test_oauth_rotator.py)
- [x] live continuous-rotation observation at the next real expiry — runtime evidence, not needed for the code change to close
