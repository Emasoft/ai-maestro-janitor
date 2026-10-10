---
trdd-id: A7KT2CL1
title: A usage-endpoint throttle makes the rotator switch accounts when a target exists
column: blocked
status: tasked
created: 2026-10-05T22:11:15+0200
updated: 2026-10-10T15:42:43+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:15+0200
blocked-by: [QHACQPPG]
pre-block-column: todo
---

# A usage-endpoint throttle makes the rotator switch accounts when a target exists

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

On a debounced 429 from the usage endpoint the tick sets near to true and rotates onto a safe, a model-spent or an unmeasured alternate. TRDD-QHACQPPG covers only the case with no target. Read from the code and a review; not observed happening.

## Approval log

- 2026-10-05T22:11:15+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Findings

2026-10-10 15:42. MEASURED by the main session, no code. READ in cmd_auto: on a usage-endpoint 429 the tick defers until the streak reaches LIVE_429_DEBOUNCE (2), then sets near and goes on to pick a target, exactly as the card says. FIELD (rotator.log.1 plus rotator.log, 2026-10-10 09:08 to 15:35): 0 lines of the live 429 branch (no 'RATE-LIMITED (429' and no 'returned 429 (streak'), and no account switch at all, so the card's case is UNOBSERVED in the retained window. The lines that do contain 429 are 31 exhausted verdicts whose tail lists an ALTERNATE account as maxed-429(x324): an alternate ruled out on a streak of 324 throttle answers from the same endpoint, which is the same doubt applied to a candidate and is not this card's case; noted here, not carded. DECISION: this card is the same choice as TRDD-QHACQPPG. Its option A (stay put on a usage-endpoint 429 while the last good reading is within limits, applied where the 429 is first judged) sits before near is set and so covers the case with a target too; option B keeps both. One decision, two cards, so this card is BLOCKED on TRDD-QHACQPPG. Not decided by the main session under the mandate because the fact that would settle it is missing: no log on disk shows whether a usage-endpoint 429 has ever coincided with a real wall. To do, item by item: investigate, done as far as the log reaches; verify, unobserved; fix, waits on QHACQPPG.
