---
trdd-id: 119JBB8C
title: Hide secrets in log files at write time and sweep closed logs
column: todo
status: tasked
created: 2026-11-05T02:58:24+0100
updated: 2026-11-05T03:11:20+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-05T02:58:24+0100
npt: [11KWFU5L]
---

# Hide secrets in log files at write time and sweep closed logs

Derived from TRDD-RPHJ64W1. Plan: (a) every janitor writer that appends to .janitor/logs or the global-state logs hides secrets before writing; (b) closed or rotated logs are swept with the plain-text mode of the transcript sweeper (TRDD-11KWFU5L); (c) a log that a process holds open with O_APPEND is never rename-replaced, because the process keeps writing to the orphaned inode. Run the redaction until the output is stable (idea: baditaflorin_agent-redact redactor.go:86-96). Open design question: the janitor writers are Python and the shield engine is TypeScript; decide between a subprocess call, a shared rule file, or a port, with a measured cost.

## Done when
 - [ ] An inventory lists every log writer with file:line.
 - [ ] Each writer hides secrets before writing, with one test per writer.
 - [ ] Closed logs are swept by the shared sweeper and open logs are skipped (checked with lsof), both tested.
 - [ ] The Python-or-TypeScript question is decided with a measured cost per log line for each option, recorded on this card.
 - [ ] The redaction is repeated until the output no longer changes, shown by a test.
 - [ ] The closed-log sweep defaults to a dry run, and its first live run waits for the owner's approval of the exact command: these logs are not in git (RULE 0 of the owner's global rules).

## Approval log

- 2026-11-05T02:58:24+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
