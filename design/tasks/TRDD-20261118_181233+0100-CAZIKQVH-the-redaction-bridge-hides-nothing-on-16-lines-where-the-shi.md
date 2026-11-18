---
trdd-id: CAZIKQVH
title: The redaction bridge hides nothing on 16 lines where the shield scanner reports an assignment finding
column: backburner
status: tasked
created: 2026-11-18T18:12:33+0100
updated: 2026-11-18T18:15:22+0100
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
approval-datetime: 2026-11-18T18:12:33+0100
---

# The redaction bridge hides nothing on 16 lines where the shield scanner reports an assignment finding

## Approval log

- 2026-11-18T18:12:33+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Symptom

By main-agent 2026-11-18: redact_texts (scripts/lib/transcript_redact.py) returned unchanged 16 lines that scan.ts reports as kind assignment: tests/agent_context_bench/corpus-vawikrk2-20260821.jsonl lines 3, 12, 13, 14, 25, 50, 59, 60, 93, 111, 113 and 140; corpus.jsonl lines 1, 4 and 238; benign-ordinary.jsonl line 27. The realtime and transcript redaction paths use the bridge, so a value the scanner sees can reach the agent or a transcript.
Not reproduced by the cheap-worker that wrote this card. The main agent equality-tested the 16 lines on 2026-11-18 with scripts_dev/triage/bridge_equal.py: redact_texts returned all 16 unchanged, with no marker of either kind. The mods expert found the same gap on the live mod path (P10 of its design report, 2026-11-18): redactDeep finds none of the 16 inside a text, redactJsonLine finds them. Increment 3a of TRDD-DSXC9MP9 is to fix it in the core.

## Suspected cause

Not known. A lead: the key and value context inside a JSON string line (design/specs/TRDD-BAQB9SYO-increment-3-redact.md, line 5, item b).

## Done means

The gap is reproduced with a fragment-built test line, its cause is found, and the bridge and the scanner agree, or the difference is documented as intended. Related: TRDD-DSXC9MP9, TRDD-Q6LPJTPO.
