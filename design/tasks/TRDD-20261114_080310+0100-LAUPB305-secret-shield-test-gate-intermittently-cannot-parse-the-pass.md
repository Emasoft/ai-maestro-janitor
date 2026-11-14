---
trdd-id: LAUPB305
title: secret-shield test gate intermittently cannot parse the pass and fail counts after claude exits 0
column: todo
status: tasked
created: 2026-11-14T08:03:10+0100
updated: 2026-11-14T09:06:41+0100
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
approval-datetime: 2026-11-14T08:03:10+0100
---

# secret-shield test gate intermittently cannot parse the pass and fail counts after claude exits 0

## Symptom
On 2026-11-14 a worker run of scripts/run_secret_shield_tests.py failed with: could not parse the pass/fail counts from the run's output. The claude plugin test output it printed stopped at line 525, with no summary lines, and claude exited 0. A re-run minutes later at load 15.5 passed (841 pass, 0 fail). Not reproduced since.

## Evidence
reports_dev/cheap-worker/20261114_080021+0100-probe-escaped-revert.md (the failing run and its output). The parse check is scripts/run_secret_shield_tests.py main(), the branch that returns the could-not-parse failure after code == 0.
Decisive facts (2026-11-14): the worker's capture of the gate's stderr (which may or may not include the gate's own FAIL line) was 78022 bytes, 525 lines, and its last line is cut mid-line inside a test name of the describe block 'the GitLab session cookie is hidden whole, the cookie name is kept'. Load was 4.16 at start and 6.01 later (near idle, so not a load effect on its face). Claude Code 2.1.325 on this host now; the version at the failure was not recorded. Copy of the output: reports_dev/run-secret-shield-tests/20261114_075700+0100-parse-failure-output.txt (gitignored). A mid-line cut means the output was truncated (by claude's flush, the gate's reader, or the worker's capture; not yet known), not that a test failed.
Second occurrence (2026-11-14, ~08:25): inside the D8 harness smoke test (tests/harness/redos_load_harness.py, run_probe, its own claude plugin test run, not the gate), at load 6.6: the non-dry probe's output had no pass/fail count lines and no header for hooks/secret-shield/tests/shield.test.ts; the dry run just before passed, and an immediate rerun passed. The output and claude's exit code were not saved. The harness reads claude's output through its own run_probe, not the gate's _run_in_own_session (the harness imports only assemble_plugin_dir; the two readers are not yet compared line by line), so two different readers saw it: the cut is not in the gate's reader alone, and is most likely in claude plugin test itself, unless both readers share a reading pattern (for example, stopping when the process exits rather than at EOF); compare the two before concluding. Two occurrences today in an uncounted number of runs (an estimate, not a count: about a dozen) make it plausible, even likely, in a 21-probe campaign.
Reproducer findings so far (2026-11-14, worker report pending; scripts_dev/laupb305/repro.py, data reports_dev/laupb305/; run4 counts read from runs.jsonl, run2 counts and the micro-test are worker-reported, not yet read from the data): every reproducer cut came through a pipe (run2 gate arm 2 of 30, run4 pipe arm 1 of about 69, mid-run), none through a regular file in about 100 file runs (run2 30 plus run4 70; run3, under load, not included); all three reproducer cuts were exactly 77931 bytes with exit 0 (growth after exit is measurable only on file runs, and no file run cut). The first real occurrence's 78022-byte capture also held the gate's FAIL line, about 91 bytes, so it may be the same 77931-byte cut (a lead, not a fact). A micro-test on this host (a Node or Bun script writing a large output then calling process.exit()) lost the tail through a pipe in 50 of 50 runs (cut at 65536 or 65500 bytes) and never through a regular file: the mechanism exists here, it does not yet show claude hits it. Working hypothesis, not yet concluded: claude exits before its last asynchronous pipe write flushes; the pending check that decides it is whether byte 77931 of a complete output is where the final summary block (or last write) starts. Candidate fix on our side: gate and harness capture claude's output to a temp regular file instead of a pipe, reading it only after no process in the session's group remains (or once it stops growing), with a test that shows the pipe loss and the file capture keeping the tail.
Worker conclusion (2026-11-14, report reports_dev/sonnet-worker/20261114_090343+0100-laupb305.md; pooled counts re-tallied by the main agent from runs.jsonl except the final run5 rows): pipe-style capture (bytes pipe arm plus the real gate reader) cut 5 of 320 runs, file capture 0 of 180 with no growth after exit; every cut 77931 bytes, exit 0, 523 newlines, ending mid-line in the same test name. In a complete output the patterns.test.ts block starts at byte 12431, so 77931 = 12431 + 65500, about 64 KiB of pipe capacity into that 116 KB block; the original 78022-byte capture is the same cut plus 91 bytes of the gate's FAIL preamble. Cut loads 4.0 to 35.9, so load is not required (4 of 5 under 8); whether heavy load raises the rate is unknown. Node and bun on this host drop output past about 64 KiB when process.exit follows pending pipe writes (50 of 50), never on a regular file; claude is bun-based. Cause: claude (or its test child) exits with pipe writes still pending; neither reader is at fault. Not cleared: the rate under heavy CPU contention (the burner batch had 4 busy processes on 14 cores). Diagnostics committed in 74799e97; the fix (capture through a regular file in both readers) follows.

## Why it matters
The gate runs inside scripts/publish.py. An intermittent false failure blocks a release; a fix that loosens the parse to make it pass would let an incomplete run ship. Fail closed stays.

## Work
1. Reproducer: run the gate N times (N >= 30) under idle and under load, record each exit, output byte length and last line.
2. On the parse-failure path, print the output byte length, line count and last 20 lines before the full output, so the next occurrence is diagnosable from the log alone.
3. Find whether the output is cut by claude itself (exit before flush) or by the reader in _run_in_own_session; fix the cause, never the check.
Note on step 2: _fail already prints the full output; the new value is the length, line count and tail printed first, so a large dump does not hide them. On N: the runs before and after the failure were not counted, so its rate is unknown; 30 clean runs argue only that the rate is below about 1 in 10, so raise N if a lower rate must be shown.
4. Make the D8 harness save the raw output of any invalid probe next to its JSONL record, so the next occurrence is diagnosable. 5. This card now blocks the D8 campaign (TRDD-OD5Z90YL step 5): at the observed rate a 21-probe campaign would likely end invalid.

## Done when
The cause is named with a reproducer, or N runs show no failure and step 2 is committed so a recurrence is diagnosable.

## Approval log

- 2026-11-14T08:03:10+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-14T08:04:49+0100 — column → todo by main-agent@ai-maestro-janitor. the gate runs inside publish.py, so this can block a release
- 2026-11-14 — straight from backburner to todo without design: a small bugfix card whose work steps are already written; a design pass would add nothing before the reproducer.

## Notes

2026-11-14: the upstream defect (claude exits with stdout pipe writes pending) is NOT reported anywhere: Claude Code's repository is not owned by this project's GitHub account, so whether to report it is the owner's decision. Our fix captures through a regular file, the capture claude writes synchronously; it is not a reader-bug fix.
