---
trdd-id: 8O9A2QRS
title: Secret shield union pass hides what the JSON-first order finds in the 1732 texts the additive order misses
column: backburner
status: tasked
created: 2026-11-18T23:53:53+0100
updated: 2026-11-18T23:55:42+0100
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
approval-datetime: 2026-11-18T23:53:53+0100
---

# Secret shield union pass hides what the JSON-first order finds in the 1732 texts the additive order misses

## Approval log

- 2026-11-18T23:53:53+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Symptom

By main-agent 2026-11-18, after commit aac5be3c (TRDD-CAZIKQVH): redactText runs the two old walks (redactDeep, redactBlocks), then walk 3 (redactTokens on each line that parses as a JSON object or array), then walk 4 (hide found values where copied, also behind escapes). In 1,732 of 200,000 generated texts the JSON-first order (redactJsonLine first) would have hidden a secret that this additive order leaves visible in part.
Union means: also run the redactJsonLine order, take the values it found, and hide them in the additive output with hideKnown. One more pass over the text. Cost of that pass is unmeasured.

## Timing risk

A 4 MB JSONL Read went from 532 ms to 1659 ms at load 10 (3.1x) with aac5be3c. The hook limit is 10 s, and a timeout after next() leaves the raw result, so a slower pass can leave a secret unredacted. Measure a 4 MB JSONL Read under load on the union build; consider a size cap for walk 3.
json-text.test.ts adds a wall-clock ratio test ("4,000 JSON lines ... less than 48 times as long as 250") that runs in the mandatory publish gate G3b. publish.py already notes that the patterns.test.ts timing ratio is load-sensitive, and this host runs at load 10 to 50, so measure the ratio's headroom at high load, or make the test robust.
Timing at heavier load: an earlier run at load 23 to 50 took about 2.5 s per MB, about 10 s for 4 MB, which is at the 10 s hook limit. (Figure as reported by the orchestrator 2026-11-18; not re-measured by the card writer.)

## Done means

The union pass is built and measured; 0 regressions against bd6bca6f (redactDeep and redactBlocks) are kept; timing is measured under load against the 10 s hook limit; or a documented decision not to build it.

## Related

TRDD-CAZIKQVH (the fix this follows, commit aac5be3c), TRDD-DSXC9MP9. Evidence: reports_dev/mods-expert-developer-agent/20261118_191313+0100-p10-json-lines.md and reports_dev/mods-expert-developer-agent/probe/p10/final-run-v8.txt.
