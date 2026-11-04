---
trdd-id: C88OZANX
title: memory transaction journal loader trusts the journal it loads
column: complete
status: archived
created: 2026-11-04T06:28:10+0100
updated: 2026-11-04T19:43:54+0100
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
implementation-commits: [f3a2313d, 5480fc77, ae41166d]
unblock-when: [trdd:90LAMQ8B]
blocked-by: []
pre-block-column: 
---

# memory transaction journal loader trusts the journal it loads

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-11-04

- 2026-11-04: Commit A (f3a2313d), Commit B (5480fc77) and the OSError follow-up of Commit B have landed; the card is blocked on TRDD-90LAMQ8B for box 3.
- NEXT ACTION: when TRDD-90LAMQ8B closes, run the full suite, ruff, mypy and pyright; if all pass, tick box 3, add ae41166d to implementation-commits, and close this card. The 31 test_repo_state errors come from the session's git configuration (measured on their own) and the 5 idle-clear failures are not yet root-caused; both have the same counts at bd6a7eca, and the idle-clear run there imported bd6a7eca's own dispatch.py, so this card did not cause them.
- Gotcha: a publish fails the full-suite gate until TRDD-90LAMQ8B is fixed: the test_repo_state errors appear when safe.bareRepository=explicit is set; the idle-clear failures are not yet understood.

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
- [x] the full test suite, ruff, mypy and pyright pass

## Approval log

- 2026-11-04T06:28:10+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-04T07:32:34+0100 — column → blocked by main-agent@ai-maestro-janitor. box 3 waits on TRDD-90LAMQ8B; no code work left on this card
- 2026-11-04T19:43:29+0100 — column → dev by main-agent@ai-maestro-janitor. TRDD-90LAMQ8B is complete (52c8f975, fd654580) Cleared blocked-by (--clear-blocker override).
- 2026-11-04T19:43+0100 — box 3 met: f3a2313d, 5480fc77 and ae41166d (committed 06:38 to 07:33) were all in the tree of the full-suite run started 18:22, which gave 18932 passed, 0 failed, 0 errors; no scripts/ commit since 18:00; ruff, mypy and pyright clean in the TRDD-90LAMQ8B follow-up runs.
- 2026-11-04T19:43:54+0100 — COMPLETE by main-agent@ai-maestro-janitor. all Done-when items met; full suite and linters green.

## Notes

- Commit A's message says the shape check "accepts what _persist writes and nothing else". What is true is that it accepts everything _persist writes. It still accepts unknown extra keys, any string for op, and an empty or relative scope_root; Commit B checks txn_id and scope_root.
- Commit A also changed two unlisted behaviours: stage_* and apply_atomic gain the same resolve()-to-MemoryTxnError conversion as begin(), and a staging journal with a negative owner_pid, which _persist never writes, is now reported as unreadable instead of reclaimed as owner-dead.
- Every _persist version since 23f6f67b writes the same 8 required fields with the same types. write_hashes (bee7266f) and owner_pid (a33ab903) came later and stay optional, so no older pending journal is stranded by the shape check.
- Commit B's message says ten new tests each fail against f3a2313d. Precisely: the 8 tests added first were run against f3a2313d's code and failed; the two later staging tests (a/../.maint-staging and .MAINT-STAGING) were shown to fail against the intermediate first-component check, not against f3a2313d; and at least one direct _load test fails on f3a2313d because of the new two-argument signature, not because of the check.
- The memgrep Rust code only skips .maint-staging when walking files (memory.rs EXCLUDED_SUBDIRS, mem_delete.rs walk_md_files); it has no journal logic. txn_id has been uuid4().hex since the first memory_txn version (23f6f67b), so no older pending journal is refused by the format check.
- The OSError that the staging-dir identity check in _ensure_rel_inside (staging.exists(), first.exists(), first.samefile()) can raise is now converted to MemoryTxnError, so begin() cleans its staging dir and the CLI reports an error instead of a traceback; test_begin_with_unstattable_source_rel_raises_and_leaves_no_staging_dir uses a 300-character first path component (a real ENAMETOOLONG) and failed on the old code.
