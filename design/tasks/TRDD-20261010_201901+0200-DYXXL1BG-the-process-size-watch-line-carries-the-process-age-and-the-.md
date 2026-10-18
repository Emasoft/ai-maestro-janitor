---
trdd-id: DYXXL1BG
title: The process-size watch line carries the process age and the size of the largest file it was given
column: testing
status: tasked
created: 2026-10-10T20:19:01+0200
updated: 2026-10-18T03:49:40+0200
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
implementation-commits: [e272b9d6]
---

# The process-size watch line carries the process age and the size of the largest file it was given

Goal: make a detection of the process-size watch classifiable afterwards from daemon.log alone. Derived from TRDD-DKID2PYP (its design step of 2026-10-10 20:20). Today the line 'process-size-watch: pid=N <label> footprint=… resident=… ceiling=…' cannot tell a large legitimate edit from a runaway: 7 of 8 field detections stay unclassified. Add two fields to that one line, written once per detection (the watch already alerts once per pid and start time): age=<seconds since the process started> (already in the row, no new read) and largest_arg_file=<N>kB, the size of the largest existing regular file among the process arguments that are absolute paths, or largest_arg_file=none. SIZE ONLY, never a name or an argument: label_from_argv deliberately shows no argument because arguments can hold secrets, and that decision stands. Known limits to write in the code: an argument given as a relative path is not seen (the process's working directory is not read); a file passed on stdin is not seen. Verify: a test with a real row and a real temporary file passed as argv shows both fields on the line; a test with a secret-looking argument shows the argument text nowhere in the line. FIELD CHECK: the next real detection in daemon.log carries both fields; cannot be seen before a release.

## Approval log

- 2026-10-10T20:19:01+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T20:27:22+0200 — column → testing. built; the field check needs a release and a detection

## Acceptance

- [x] The detection line carries age and largest_arg_file, and no argument text or data-file name: pinned by test_detection_line_carries_age_and_the_largest_arg_file_size, test_detection_line_ignores_the_interpreters_script and test_detection_line_never_shows_an_argument_or_a_file_name on real child processes (tests/test_process_size_watch.py, 26 passed on the main session's own re-run).
- [ ] FIELD: the next real process-size-watch detection in daemon.log carries both fields. Cannot be seen before a release.
2026-10-10 20:27 BUILT, tests first, by one lean-worker (0.15 million tokens, 3 passes, about 7 minutes of work); the main session read the whole final diff. CORRECTIONS to the body, from the reviews: 'never a name' holds for the NEW field only; the label already shows the script name of an interpreter run, by design, and that is unchanged. The interpreter's script is excluded from the size (for a tool started as python script file, the script would otherwise have been the figure). An argument --flag=/abs/path counts. LIMITS: a relative-path argument and a file on stdin are not seen, so the field can read none on a real edit, and this was not checked against the arguments of any of the 8 field detections; any absolute-path argument counts, so a model or config file can be the figure; symlinks are followed; the stat runs on the watch thread once per detection and a hung network mount would stall that pass; the age assertion (0 to 60 s) can hardly fail and does not prove the arithmetic.
