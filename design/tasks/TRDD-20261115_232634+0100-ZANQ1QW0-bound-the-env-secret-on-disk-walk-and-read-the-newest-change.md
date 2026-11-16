---
trdd-id: ZANQ1QW0
title: Bound the env-secret-on-disk walk and read the newest change first, then schedule it
column: dev
status: tasked
created: 2026-11-15T23:26:34+0100
updated: 2026-11-16T11:47:57+0100
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

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-11-16

- 2026-11-16 increment 1 (trash tier, design item 2) landed in 54674cc4: .trashcan batch folders are read by name from saved per-batch positions, not by modification time. Two real passes of the new detector on this project took 34.8 s and 13.1 s in total (the walk alone took 28.1 s before), with 0 hits; a state file from before the change keeps its cursor and flagged list. Not released yet. NEXT ACTION: superseded by the increment 2 line at the end of this STATE block. Follow-up: TRDD-XNZFKX0L (a CRED-002 finding withdrawn for a file that was not read).

Follow-up of TRDD-G14LKPEC (issue 354). env-secret-on-disk is on demand only; tests/test_env_secret_on_disk_registration.py pins it off the roster. Fix before scheduling it. (1) Bound the walk: the time and byte budget must also cover listing and stat (today started = clock() runs after the walk in env_secrets.sweep), for example stop the walk at the budget and resume from a saved position, or skip folders unchanged since the last pass. (2) Read new changes before the backlog, so a fresh leak is found on the next pass. Then add back the roster row, the cadence option, the doctor and fleet-status entries, the quiet-heartbeat security entry and the two README rows (patch kept at reports_dev/fanout-apply/scratch/inc2/step10-schedule.patch, gitignored), and flip the registration test. Measured numbers are in the TRDD-G14LKPEC Approval log.
- 2026-11-16 increment 2 (listing bound, design item 3) landed in 9a1cea8c: the clock starts before the listing, the listing has a 30 s share (LISTING_BUDGET_S), and a cut listing moves no state and prints a coverage line once a day. Two real passes after it, at load 13 to 14: 35.2 s and 40.9 s in total, no cut, 0 hits, 455,681 files left for later passes (the backlog grew by a 199,366-file scratch copy under reports_dev/zanq1qw0/mutation that the owner must decide on before the schedule done-when measurement). Not released yet. NEXT ACTION: increment 3 (design items 4 and 5, spelled out in the Design section), then the schedule.
- 2026-11-16 increment 3 (newest first, design items 4 and 5) landed in c0e14873: a covered range [lo, hi] replaces the cursor, the fresh tier (keys above hi, ascending) has half the pass budget, the backlog below lo is read newest first, each tier reads at least one file per pass, and hi never moves above the live edge. Two real passes after it, at load 6 to 7: 48.5 s and 56.2 s in total, 0 hits; the first pass read the newest files of this session first, and its 3 dump-shape flags were copies of the test value OTHER_API_KEY in worker output; 463,026 files left (the 199,366-file scratch copy under reports_dev/zanq1qw0/mutation still counts). Not released yet. NEXT ACTION: TRDD-XNZFKX0L, then the schedule (patch reports_dev/fanout-apply/scratch/inc2/step10-schedule.patch), whose done-when measurement waits on the owner decision about that scratch copy.
- 2026-11-16 schedule hold: the heartbeat stub os.execv-s into dispatch.py, which runs each due detector with a blocking subprocess.run (120 s timeout) inside the fire, so a fire that runs this detector lasts at least its pass (48.5 s and 56.2 s measured after increment 3) plus up to about 15 s of trash tier (that budget is checked per entry, so one large folder listing can run past it). The pass line gives no per-phase seconds. Before applying the schedule patch: add per-phase seconds to the pass line, re-measure, and get an advisor verdict on the hourly cadence and the budget.

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
Increment 3 (items 4 and 5), advisor-reviewed 2026-11-16. State: covered = [lo, hi], two (mtime, path) keys; every key inside it was read. The old cursor key is dropped, not migrated: migrating it as [(0, empty path), cursor] would make every file above it the fresh tier, read oldest first, which is the present order.
Increment 3, absent covered key: lo = hi = (live edge, empty path), so the first pass reads newest first; flagged, retries and trash are kept, as in increment 1.
Increment 3, live edge = wall time at the start of the listing minus LIVE_EDGE_MARGIN_S (2 s). hi never moves above it: a file written during the listing into a folder already walked has a later mtime, and an hi moved past it by a newer file listed later would cover it unread. A file above the edge is still read, and read again next pass.
Increment 3, tiers: the fresh tier is the keys above hi, read ascending (contiguity forces it, so inside the fresh tier the order is still oldest first; newest first holds between the tiers), with FRESH_SHARE (0.5) of the byte budget and of the time left after the listing. The backlog is the keys below lo, read descending, with the rest of the pass budget. Each tier reads at least one file per pass, so a fresh file larger than the whole budget cannot stop the backlog.
Increment 3, holds go to their own edge: hi stops below the lowest fresh hold, lo stops above the highest backlog hold. A listing cut or a failing git keeps both edges. The raise order under the per-fire cap follows each edge: fresh hits ascending, then backlog hits descending, then trash hits by path.
Increment 3, known limit: a file whose mtime is in the future (clock skew, or touch with a later date) stays above the live edge, so it is read again on every pass inside the fresh share; it costs at most that share and never stops the backlog, which has its own at-least-one-file guarantee.
