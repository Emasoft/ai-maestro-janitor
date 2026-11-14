---
trdd-id: A7RII4DN
title: Secret shield jwt rule is superlinear on a long eyJ run
column: complete
status: archived
created: 2026-11-14T01:34:49+0100
updated: 2026-11-14T02:36:30+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: security
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-14T01:34:49+0100
implementation-commits: [4970ff1f]
---

# Secret shield jwt rule is superlinear on a long eyJ run

## Approval log

- 2026-11-14T01:34:49+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-14T02:36:30+0100 — COMPLETE by main-agent@ai-maestro-janitor. jwt rule linear with identical spans in 4970ff1f; 1 MB timing case added in the closing commit; old rule fails the timing tests.

## Why

Worker probe 2026-11-14 (report path above, out/quad.log): 64 KB of eyJ- repeated takes about 600 ms with the current jwt rule (rules/key-material.ts:15) and about 604 ms with the widened candidate; 16 KB takes 40 ms, so the cost grows about 15x for 4x input. Extrapolated, not measured: about 9 s at 256 KB, near the assumed 10 s hook limit (TRDD-U5O72MGA). Same class as U5O72MGA.

## Done when

The jwt rule's time on 256 KB and 1 MB of the repeated run is measured; if it can exceed the hook limit, the rule is bounded (fail closed, test) or the case is recorded with a bound.
- [x] 256 KB and 1 MB measured (Notes).
- [x] The jwt rule is linear with the same spans, pinned by tests that fail on the old rule.
- [x] Orchestrator commits key-material.ts, patterns.test.ts and this card, then closes the card.

## Notes

- 2026-11-14: measured, single runs on an uncontrolled host, not a threshold. Old rule, worst input (eyJ- repeated): bun 16 KB 39 ms, 64 KB 614 ms, 256 KB 9.8 s, 1 MB over 60 s (killed). Plugin engine (claude plugin test): old rule 256 KB 2.5-2.7 s per case (4 cases, each over the 1 s bound). New rule, plugin engine: 256 KB 2.5-3 ms per case, 1 MB valid-token cases 10-15 ms; bun prototype 1 MB 7-45 ms.
- Changed: hooks/secret-shield/rules/key-material.ts jwt rule now anchors at a run start (?<![A-Za-z0-9_-]), tests the tail once in an atomic lookahead, skips to the leftmost eyJ with a lazy class loop, and matches the old token unchanged as group 1. Same spans as before (not widened, not narrowed). applyRule (patterns.ts:217) hides only group 1 and keeps the prefix before it, so output and hit counts are identical.
- Equivalence: the first segment class excludes the dot, so every eyJ start inside one run of [A-Za-z0-9_-] must reach the run end; all starts in the run share the fate of the tail (.eyJ, 10+, ., 10+), and the old result is the leftmost start with a boundary before eyJ and 10+ characters before the run end. Differential check: 200000 seeded random strings (15540 with a match) gave 0 span differences between the old and new regex (scratch run), and the committed test pins 400 seeded strings plus 18 hand cases.
- Suite (claude plugin test on a scratch shell): baseline 682 pass; new tests on the old rule 703 pass 5 fail (TOKEN_ORDER pin and the four 256 KB timing cases; 1 MB tests shrunk to 1 KB in that copy because the old rule takes minutes); new tests on the new rule 708 pass 0 fail (682 + 26 new).
- 2026-11-14: landed in 4970ff1f; review added a 1 MB timing case (old rule at 512 KB: 39629 ms on a scratch copy).
