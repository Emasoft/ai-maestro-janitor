---
trdd-id: PAHO6KWK
title: The rotator wedge tick sets its env flag in the whole daemon process so other threads' subprocesses inherit it
column: todo
status: tasked
created: 2026-10-06T17:25:57+0200
updated: 2026-10-06T17:25:57+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T17:25:57+0200
---

# The rotator wedge tick sets its env flag in the whole daemon process so other threads' subprocesses inherit it

scripts/daemon.py ~3422-3426: the tick thread sets os.environ["JANITOR_ROTATOR_WEDGE_TICK"]="1" around task.run() and pops it in a finally. os.environ is process-global: while a wedge tick runs, every subprocess any other daemon thread starts (main-loop chores, the process-size watch's ps) inherits JANITOR_ROTATOR_WEDGE_TICK=1, and mutating the environment while another thread forks is not thread-safe. Fix: pass the flag only in the rotator subprocess env (env={**os.environ, "JANITOR_ROTATOR_WEDGE_TICK": "1"}) instead of mutating os.environ; a test that fails before (another thread's subprocess sees the flag) and passes after. Found by the review of a4426a8e (the test race fix), 2026-10-06.

## Approval log

- 2026-10-06T17:25:57+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
