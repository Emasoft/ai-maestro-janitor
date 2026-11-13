---
trdd-id: U5O72MGA
title: Secret shield JSON_ESCAPED pass is quadratic on a long backslash run
column: todo
status: tasked
created: 2026-11-13T23:41:03+0100
updated: 2026-11-13T23:41:03+0100
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
approval-datetime: 2026-11-13T23:41:03+0100
---

# Secret shield JSON_ESCAPED pass is quadratic on a long backslash run

Found during the change-2 measurements of TRDD-AGOEWF2E. Measured 2026-11-13 by one worker run in the plugin engine (claude plugin test on a scratch copy of hooks/secret-shield, load 4 to 10, not re-run by the main agent). Recipe: redact() on a text that is only a run of n backslashes, and on a pair opening followed by n/2 escaped-backslash pairs. At about 108K backslashes redact() took 5.1 s (5,077 ms after the AGOEWF2E change, 5,182 ms before) and 4.5 s for the escaped-pairs shape: one size, measured twice, not a curve. Suspected cause, by reading, not by isolation: the JSON_ESCAPED pattern of hooks/secret-shield/patterns.ts starts with a backslash run before a quote, so with the g flag every start position in a run of n backslashes takes the run greedily and backtracks, O(n) per start and O(n²) overall. Extrapolated, not measured: about 150K backslashes would take about 10 s. The time was measured for all of redact(), so another pass may share it. Open question that decides severity: when the secret-shield hook runs out of time, does the tool result reach the model unredacted (fail open) or is it withheld (fail closed)? Done when: (1) the shield hook's time limit is found, its source named, and its behaviour on running out of time measured and written down; (2) the costly pass is isolated, the growth is measured at a second size (for example 54K against 108K backslashes), and either that pass is linear on a backslash run (a test with 1 MB of backslashes under a stated time, red on the old rule) or redact() withholds a text it cannot finish in time, shown by a test; (3) TRDD-2V7OAUPE is unblocked once (1) is done, and additionally needs (2) only if (1) shows the hook fails open.

## Approval log

- 2026-11-13T23:41:03+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
