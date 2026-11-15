---
trdd-id: 7XDBJZCZ
title: A deterministic llm-ext classify refusal is mapped to kind unknown and retried for the whole 300 s Jev budget
column: todo
status: tasked
created: 2026-11-15T17:41:44+0100
updated: 2026-11-15T17:41:44+0100
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
approval-datetime: 2026-11-15T17:41:44+0100
---

# A deterministic llm-ext classify refusal is mapped to kind unknown and retried for the whole 300 s Jev budget

MAIN-VERIFIED 2026-11-15 (code read): scripts/lib/jev_compaction.py raises a plain JevError for every 'llm-ext classify filter' failure (:1233 non-zero exit, plus the no-report and malformed-report cases after it); scripts/jev_compact.py maps a plain JevError to kind 'unknown' (:287); scripts/lib/jev_compaction_lane.py treats 'unknown' as transient and sleeps 15 s and retries until the Jev deadline (:1505-1520 region, 'unavailable / unreachable / unknown / a missing kind'). So a refusal that cannot change between attempts (seen today: 'Path traversal blocked', fixed in db4db2d5 for that one cause, TRDD-2GCJ5D3M; others possible: an unknown --profile, a bad flag) burns the full 300 s before the llm-ext fallback, about 283 s on the 16:46 clear today. TO DO FIRST: list the llm-ext exit codes and stderr shapes for deterministic refusals vs network or rate-limit failures (llm-externalizer source), then raise a non-retryable JevError subclass (mapped to 'invalid', already in _NON_RETRYABLE_KINDS) for the deterministic ones. Acceptance: a test where the stand-in llm-ext exits with a path-refusal message shows one Jev attempt, then the fallback; a transient failure still retries.

## Approval log

- 2026-11-15T17:41:44+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
