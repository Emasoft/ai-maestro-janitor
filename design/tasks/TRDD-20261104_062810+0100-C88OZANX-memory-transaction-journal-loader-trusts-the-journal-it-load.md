---
trdd-id: C88OZANX
title: memory transaction journal loader trusts the journal it loads
column: dev
status: tasked
created: 2026-11-04T06:28:10+0100
updated: 2026-11-04T06:38:20+0100
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
approval-datetime: 2026-11-04T06:28:10+0100
---

# memory transaction journal loader trusts the journal it loads

## Problem
scripts/lib/memory_txn.py MemoryTxn._load builds a transaction from a journal file under <scope>/.maint-staging/ and trusts it in two ways. (1) Robustness: a journal that is not valid UTF-8, not a JSON object, or has wrongly typed fields raises an exception the callers do not catch, so one bad journal stops resume_pending and leaves every later journal unprocessed (M-7 says it must not), and commit and abort print a traceback instead of an error. (2) Containment: the journal's own scope_root and txn_id decide which paths resume, commit and abort delete, and M-10's containment check is anchored on that same journal-supplied scope_root, so a crafted journal can direct a delete outside its scope.

## Reachability
Latent, manual trigger only. resume_pending, commit and abort run only through scripts/memory_txn_cli.py; no heartbeat, detector, skill, agent or hook calls them (checked 2026-11-04). The staging directory is gitignored in this repo.

## Plan
- Commit A: narrow parse-error handling plus an explicit shape check in _load; resolve() failures in _ensure_rel_inside become MemoryTxnError.
- Commit B: _load takes the trusted scope from its caller and refuses a journal whose scope_root is not that scope, whose txn_id is not 32 lowercase hex, or whose file name does not match its txn_id; rels may not point into .maint-staging; the CLI validates its txn_id argument.

## Done when
- [x] Commit A lands with tests that fail on the old code
- [ ] Commit B lands with tests that fail on the old code
- [ ] the full test suite, ruff, mypy and pyright pass

## Approval log

- 2026-11-04T06:28:10+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
