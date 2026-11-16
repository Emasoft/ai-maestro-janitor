---
trdd-id: ZANQ1QW0
title: Bound the env-secret-on-disk walk and read the newest change first, then schedule it
column: backburner
status: tasked
created: 2026-11-15T23:26:34+0100
updated: 2026-11-16T10:08:08+0100
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
approval-datetime: 2026-11-15T23:26:34+0100
---

# Bound the env-secret-on-disk walk and read the newest change first, then schedule it

Follow-up of TRDD-G14LKPEC (issue 354). env-secret-on-disk is on demand only; tests/test_env_secret_on_disk_registration.py pins it off the roster. Fix before scheduling it. (1) Bound the walk: the time and byte budget must also cover listing and stat (today started = clock() runs after the walk in env_secrets.sweep), for example stop the walk at the budget and resume from a saved position, or skip folders unchanged since the last pass. (2) Read new changes before the backlog, so a fresh leak is found on the next pass. Then add back the roster row, the cadence option, the doctor and fleet-status entries, the quiet-heartbeat security entry and the two README rows (patch kept at reports_dev/fanout-apply/scratch/inc2/step10-schedule.patch, gitignored), and flip the registration test. Measured numbers are in the TRDD-G14LKPEC Approval log.

## Approval log

- 2026-11-15T23:26:34+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Design 2026-11-16 (advisor-reviewed, supersedes the one-paragraph plan in the body)

Rule: an mtime edge may move only over a COMPLETE listing; a path-order position is sound only on a tree that is never rewritten.
Facts read 2026-11-16 (code, read-only):
- env_secrets.sweep lists and stats every file under every root before started = clock(); only the reading is budgeted (env_secrets.py sweep).
- One cursor (mtime, path) in .janitor/state/env-secret-on-disk.cursor.json; advance_cursor moves it past every key read.
- _untracked_files uses git ls-files --others --exclude-standard; .gitignore:103 ignores /.trashcan/*, so trash files never come back as untracked roots.
- .trashcan holds 26 timestamp batches (952,625 of ~1.2M files, 11-15 measurement). safe_delete.py makes one batch per run, name to the second, mkdir exist_ok=True (line 325): same-second runs share a batch; a restore moves files out; memory_migrate.py:436 writes .trashcan/migrate-memory-scope/<stamp>; an agent may mv by hand.
- Moved files keep their old mtime, so the present cursor never sees new trash arrivals (detector docstring lines 19-20).
Design:
1. MEASURE first, after the publish, at normal load: per root, time git ls-files, the listing+stat, and the reads; count files per root. The table decides the budget split.
2. Trash tier: scan settled batches (name older than 120 s) by batch name, newest first, walking each batch in sorted order with a saved (batch, relative path) position; no mtime. Cut anywhere, never re-walked. Drop purged batch names from state. Known gap, stated in the docstring: a file mv-ed by hand into an already-scanned batch is not read.
3. Other roots: listed in full every pass, clock started BEFORE the walk. If the listing overruns its share: move no state, print a coverage line. No directory-mtime pruning (misses in-place appends, and a deep change does not touch parent folders).
4. Newest first: state holds a covered interval [lo, hi]. Read above hi ascending, then below lo descending. New state shape, no migration (regenerated state; the old cursor sits at 0.3 percent).
5. Starvation check before 4 lands: if the same growing files lead two passes (live transcripts via scratch links, .janitor/logs), cap the fresh tier byte share so the backlog always advances.
Landing: items 2-5 share the state file, so design them once on the card; land as three increments: bound (3), order (4,5), trash tier (2); then schedule (patch reports_dev/fanout-apply/scratch/inc2/step10-schedule.patch, git apply --check passed 2026-11-16 at 4da6f455; re-run then). Done-when for scheduling: a re-measured pass on this repo inside the 60 s budget, not a green unit test.
Measured 2026-11-16 10:07 (design step 1, load 5.7 to 8.4 on 14 cores, scripts_dev/zanq_measure.py, the sweep's own listing and stat loop, no file read): git ls-files --others 0.01 s, 0 files; .trashcan 19.45 s for 951,892 files; docs_dev 5.68 s for 180,013 files (26 GiB); reports_dev 0.91 s (34,651); downloads_dev 0.73 s; scripts_dev 0.47 s; session scratch 0.49 s; the rest under 0.4 s. Walk total 28.1 s, about half of the 60 s pass budget before any file is read; .trashcan is 69 percent of it.
Landing order changed by that table: the trash tier (design item 2) lands FIRST, then the listing bound (item 3), then newest-first order (items 4 and 5), then the schedule. A bound that lands first would refuse to move state on most passes, because the full listing alone nears its share while .trashcan is still walked.
