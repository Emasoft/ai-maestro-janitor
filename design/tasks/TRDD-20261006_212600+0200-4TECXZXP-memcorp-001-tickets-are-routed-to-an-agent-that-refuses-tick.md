---
trdd-id: 4TECXZXP
title: MEMCORP-001 tickets are routed to an agent that refuses ticket work and dispatched without re-validation
column: todo
status: tasked
created: 2026-10-06T21:26:00+0200
updated: 2026-10-06T22:04:56+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:26:00+0200
implementation-commits: [27974a16]
---

# MEMCORP-001 tickets are routed to an agent that refuses ticket work and dispatched without re-validation

Source: GitHub issue Emasoft/ai-maestro-janitor#324 (opened 2026-09-30). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: Memory corpus tickets are routed to the memory subconscious agent, which refuses them, and the repair agent they are re-dispatched to also refuses. They are also titled with the wrong scope and dispatched without re-validation. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:26:00+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## STATE

landed on main as 27974a16; ships in the next release; issue stays open until then.
