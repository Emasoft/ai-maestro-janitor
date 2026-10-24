---
trdd-id: A56E22AL
title: The daily drift dedupe silences the ticket-dispatch NEEDS A HUMAN line
column: todo
status: tasked
created: 2026-10-24T11:42:23+0200
updated: 2026-10-24T11:42:23+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-24T11:42:23+0200
---

# The daily drift dedupe silences the ticket-dispatch NEEDS A HUMAN line

Found by the TRDD-F3LVCQ39 census. ticket-dispatch.py:155 says the NEEDS A HUMAN line must never go quiet and must surface every fire. dispatch.py _dedupe_drift_text (:1191) suppresses a line already printed today for every detector not in _SELF_DEDUPING_DETECTORS (:1161), and the elapsed-time rule blanks the 'marked Nd ago' digits, so the line prints at most once per local day (read in code). ACCEPTANCE: decide which contract wins (the detector's every-fire promise, or the daily cap), make the code and the comment agree, and test it.

## Approval log

- 2026-10-24T11:42:23+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
