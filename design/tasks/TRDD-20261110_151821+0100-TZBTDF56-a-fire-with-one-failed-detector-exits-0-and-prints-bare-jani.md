---
trdd-id: TZBTDF56
title: a fire with one failed detector exits 0 and prints bare janitor-quiet
column: todo
status: tasked
created: 2026-11-10T15:18:21+0100
updated: 2026-11-10T15:18:21+0100
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
approval-datetime: 2026-11-10T15:18:21+0100
---

# a fire with one failed detector exits 0 and prints bare janitor-quiet

From issue #342 (tier E of the 2026-11-10 reconciliation on FQVEILVK): when a detector exits non-zero or times out, dispatch.py records error:rc=N in the streak stamp and ledger, re-emits the detector's defanged stderr (which may be a traceback, a compact line, or empty depending on what the detector printed), but main() still returns 0 and _emit_quiet_if_idle prints a bare [janitor-quiet]. A partially-failed fire is indistinguishable from a clean pass by exit code and marker; the degraded fact lives only in the ledger stamp and stderr. Fix must preserve TRDD-P64SR014's noise dedupe (3-streak batching) while making the degraded state observable per-fire without a full traceback; candidate shapes: a [janitor-degraded] marker naming the detector (requires a matching heartbeat-protocol rule row), or one concise stdout drift line per failing detector. Design choice needs the owner or a proposal.

## Approval log

- 2026-11-10T15:18:21+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
