---
trdd-id: XNZFKX0L
title: A CRED-002 finding is withdrawn for a file the env-secret sweep did not read
column: todo
status: tasked
created: 2026-11-16T10:28:03+0100
updated: 2026-11-16T10:28:03+0100
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
approval-datetime: 2026-11-16T10:28:03+0100
---

# A CRED-002 finding is withdrawn for a file the env-secret sweep did not read

In scripts/detectors/env-secret-on-disk.py, main() withdraws a CRED-002 finding for every flagged path that is "rescanned and clean now" (line 274: `if path in keys or path in trash_seen`). But `keys` (line 186) is built from report.processed AND report.failed, so a flagged file whose read FAILED this pass is withdrawn although it was not read. report.processed also holds files that were not read: a file over MAX_FILE_BYTES (the too_big branch of env_secrets._read_one) and a file whose reads failed too often (the give_up return of env_secrets._read_one). The trash tier of TRDD-ZANQ1QW0 increment 1 already excludes failed reads from trash_seen, but its processed_by_batch has the same too-big and give-up entries. Fix: withdraw a finding only for a path that was actually read this pass (a read-and-scanned set), in both tiers; a failed, too-big or given-up file keeps its finding. Test: one flagged file per case (failed read via chmod 0, too big, given up), each must stay in flagged after a pass. Found by the harness review of the ZANQ1QW0 increment 1 fixes on 2026-11-16. Related: TRDD-ZANQ1QW0, GitHub issue 354.

## Approval log

- 2026-11-16T10:28:03+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
