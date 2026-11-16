---
trdd-id: G3DB7NCW
title: The resume text does not say that a multi-part llm-ext handoff ends with its newest state
column: backburner
status: tasked
created: 2026-11-16T10:35:05+0100
updated: 2026-11-16T10:35:05+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: docs
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-16T10:35:05+0100
---

# The resume text does not say that a multi-part llm-ext handoff ends with its newest state

A handoff composed by /janitor-write-handoff from a long session holds the llm-ext per-chunk summaries joined as "--- Part N of M ---" (joinChunkSummaries in the llm-externalizer repo, scripts/llm-ext/src/session_summary/driver.ts, since de8cc80b). Each part has its own Next Step, and only the last part's is current. Seen in a 2026-11-14 handoff (two parts, 140 lines). Nothing in the janitor's resume directive or handoff injection says to read the last part first, so a resuming session can act on part 1's stale Next Step. Candidate fix: one sentence in the resume text where a handoff is pointed at. Related: TRDD-C9CO0I7L, GitHub issue 356.

## Approval log

- 2026-11-16T10:35:05+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
