---
trdd-id: BBGDUCSE
title: A failed ESC nudge at a usage-limit wedge requests no early rotation when the diagnosis is frozen
column: backburner
status: tasked
created: 2026-10-17T11:50:57+0200
updated: 2026-10-17T11:50:57+0200
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
approval-datetime: 2026-10-17T11:50:57+0200
---

# A failed ESC nudge at a usage-limit wedge requests no early rotation when the diagnosis is frozen

Split from TRDD-315X5OWA (F3 of docs_dev/20261017_114713+0200-315X5OWA-scope.md; review in that session). daemon.py requests gs.request_rotator_tick('retry-wedged-esc') only for diagnosis retry_wedged; a frozen pane whose ESC nudge FAILS at a retry_wedge screen requests none, so a persisting usage wall waits for the scheduled rotation while attempts are charged toward crash_loop/FLEET-GIVE-UP. BEFORE BUILDING (review must-fix): (1) apply only to a USAGE-LIMIT wedge, with the same discriminator retry_wedged uses (a retry line for an API/network error must never rotate an account); (2) verify request_rotator_tick's dedupe so a failed nudge every beat cannot storm the rotator; (3) decide whether a requested rotation stops charging the attempt budget or is an accepted cost; (4) log in the FIRE-FAILED line that a rotation was requested and what the rotator decided; (5) choose the key: the pane state before the ESC or the observed state after act (docs_dev/20261017_115011+0200-315X5OWA-measure.md). Effect is unverified: a rotation cured the 2026-10-09 19:57 case, but whether an EARLIER tick would have helped is not shown. Wait for TRDD-315X5OWA's F1 log lines (reads/presses) before deciding scope.

## Approval log

- 2026-10-17T11:50:57+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
