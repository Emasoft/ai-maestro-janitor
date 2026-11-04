---
trdd-id: C88OZANX
title: memory transaction journal loader trusts the journal it loads
column: dev
status: tasked
created: 2026-11-04T06:28:10+0100
updated: 2026-11-04T07:19:27+0100
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
implementation-commits: [f3a2313d]
---

# memory transaction journal loader trusts the journal it loads

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-11-04

- 2026-11-04: Commit A (f3a2313d) and Commit B (scope anchoring) have landed.
- NEXT ACTION: add Commit B's SHA to implementation-commits, and turn an OSError from the staging-dir identity check in _ensure_rel_inside into MemoryTxnError (today it gives commit and abort a traceback). Box 3 waits on 5 failures in tests/test_dispatch_phases.py and 31 errors in tests/test_repo_state.py (a failing git symbolic-ref in their fixtures); the same counts occur at f3a2313d, so they are not caused by this card.
- Gotcha: the publish gate runs the full suite, so the pre-existing failures named above block a publish until they are fixed.

## Problem
scripts/lib/memory_txn.py MemoryTxn._load builds a transaction from a journal file under <scope>/.maint-staging/ and trusts it in two ways. (1) Robustness: a journal that is not valid UTF-8, not a JSON object, or has wrongly typed fields raises an exception the callers do not catch, so one bad journal stops resume_pending and leaves every later journal unprocessed (M-7 says it must not), and commit and abort print a traceback instead of an error. (2) Containment: the journal's own scope_root and txn_id decide which paths resume, commit and abort delete, and M-10's containment check is anchored on that same journal-supplied scope_root, so a crafted journal can direct a delete outside its scope.

## Reachability
Latent, manual trigger only. resume_pending, commit and abort run only through scripts/memory_txn_cli.py; no heartbeat, detector, skill, agent or hook calls them (checked 2026-11-04). The staging directory is gitignored in this repo.

## Plan
- Commit A: narrow parse-error handling plus an explicit shape check in _load; resolve() failures in _ensure_rel_inside become MemoryTxnError.
- Commit B: _load takes the trusted scope from its caller and refuses a journal whose scope_root is not that scope, whose txn_id is not 32 lowercase hex, or whose file name does not match its txn_id; rels may not point into .maint-staging; the CLI validates its txn_id argument.

## Done when
- [x] Commit A lands with tests that fail on the old code
- [x] Commit B lands with tests that fail on the old code
- [ ] the full test suite, ruff, mypy and pyright pass

## Approval log

- 2026-11-04T06:28:10+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Notes

- Commit A's message says the shape check "accepts what _persist writes and nothing else". What is true is that it accepts everything _persist writes. It still accepts unknown extra keys, any string for op, and an empty or relative scope_root; Commit B checks txn_id and scope_root.
- Commit A also changed two unlisted behaviours: stage_* and apply_atomic gain the same resolve()-to-MemoryTxnError conversion as begin(), and a staging journal with a negative owner_pid, which _persist never writes, is now reported as unreadable instead of reclaimed as owner-dead.
- Every _persist version since 23f6f67b writes the same 8 required fields with the same types. write_hashes (bee7266f) and owner_pid (a33ab903) came later and stay optional, so no older pending journal is stranded by the shape check.
