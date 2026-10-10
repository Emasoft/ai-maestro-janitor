---
trdd-id: DYXXL1BG
title: The process-size watch line carries the process age and the size of the largest file it was given
column: todo
status: tasked
created: 2026-10-10T20:19:01+0200
updated: 2026-10-10T20:20:57+0200
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
approval-datetime: 2026-10-10T20:19:01+0200
derived: true
parent-trdd: DKID2PYP
---

# The process-size watch line carries the process age and the size of the largest file it was given

Goal: make a detection of the process-size watch classifiable afterwards from daemon.log alone. Derived from TRDD-DKID2PYP (its design step of 2026-10-10 20:20). Today the line 'process-size-watch: pid=N <label> footprint=… resident=… ceiling=…' cannot tell a large legitimate edit from a runaway: 7 of 8 field detections stay unclassified. Add two fields to that one line, written once per detection (the watch already alerts once per pid and start time): age=<seconds since the process started> (already in the row, no new read) and largest_arg_file=<N>kB, the size of the largest existing regular file among the process arguments that are absolute paths, or largest_arg_file=none. SIZE ONLY, never a name or an argument: label_from_argv deliberately shows no argument because arguments can hold secrets, and that decision stands. Known limits to write in the code: an argument given as a relative path is not seen (the process's working directory is not read); a file passed on stdin is not seen. Verify: a test with a real row and a real temporary file passed as argv shows both fields on the line; a test with a secret-looking argument shows the argument text nowhere in the line. FIELD CHECK: the next real detection in daemon.log carries both fields; cannot be seen before a release.

## Approval log

- 2026-10-10T20:19:01+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
