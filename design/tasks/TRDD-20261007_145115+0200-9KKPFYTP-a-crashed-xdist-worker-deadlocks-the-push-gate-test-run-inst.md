---
trdd-id: 9KKPFYTP
title: A crashed xdist worker deadlocks the push gate test run instead of failing it
column: testing
status: tasked
created: 2026-10-07T14:51:15+0200
updated: 2026-10-07T19:57:22+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T14:51:15+0200
implementation-commits: [a420ccfa]
---

# A crashed xdist worker deadlocks the push gate test run instead of failing it

Observed 2026-10-07 during the 3.8.7 publish. The pre-push hook re-runs the full pytest suite with xdist and -x. At 99% one worker (gw6) crashed with 'node down: Not properly terminated' while host load was over 100. The run then deadlocked from 13:43: stack samples showed the controller waiting to read from its workers and every worker waiting to read from the controller, all at 0% CPU, and a replacement worker idle. The per-test 300 s timeout cannot break it because no test is running. It was ended by stopping the controller, the push was refused, and the rerun later passed. The same suite passed twice that day under the same flags, so the crash is most likely a load flake; the bug is the hang.

Investigate: installed pytest-xdist is 3.8.0 (checked 2026-10-07). Whether --max-worker-restart=0 makes a crash fail the run cleanly, and an outer wall-clock limit on the hook's test run.

Facts (verified 2026-10-07 by reading scripts/publish.py): both test call sites run `subprocess.run(_PYTEST_CMD, timeout=_TEST_SUITE_TIMEOUT_SEC)` (3600 s) with no new session and no output capture: the gate's G4 at publish.py:1474 and step 3 through run() at :1732. INFERRED, not tested: On timeout Python kills only the direct child, `uv`, so the pytest controller and its xdist workers survive as orphans; with no captured pipes there is no wait on them afterwards. A second outer bound, _PUSH_TIMEOUT_SEC (publish.py:268), wraps the whole push. The 13:43 hang never reached the 3600 s bound: the retry run started 13:24 and its log stopped changing at 14:08, when the controller was stopped by hand. Also check: whether pytest-xdist 3.8.0 with --max-worker-restart=0 fails the run on a worker crash instead of hanging; starting the test run in its own session (start_new_session=True) and killing the whole process group on timeout. Acceptance: a killed xdist worker makes the gate exit non-zero within 5 minutes of the kill, and a process-table snapshot taken after the gate exits shows no surviving pytest or xdist process from that run; proven by a real test that runs the scenario in a child pytest process with its own hard timeout, so a regression cannot hang the suite that runs it. The line under the Approval log dated 2026-10-07T14:56:30 was misfiled there by the card tool; this paragraph supersedes it.

## Approval log

- 2026-10-07T14:51:15+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-10-07T14:56:30+0200: the gate runs `uv run --extra dev pytest tests/ -x -q --tb=short -n auto --dist loadgroup --timeout=300 --timeout-method=thread` (scripts/publish.py _PYTEST_CMD, line 225); the pre-push hook is git-hooks/pre-push (line 48 runs `uv run python scripts/publish.py --gate`). The only outer wall-clock limit on the hook's pytest run is _TEST_SUITE_TIMEOUT_SEC = 3600 s (scripts/publish.py:185, applied at :1475 and :1733); the hook itself has no timeout. It did not end the 13:43 hang because the run was stopped by hand before 3600 s elapsed (stop time not recorded, so this is inferred). The crashed test was not identified, because the log did not name it. The acceptance test must run the deadlock scenario in a child pytest process with its own hard timeout, so a regression cannot deadlock the suite that runs it.
2026-10-07T15:02:30+0200: the process check in the acceptance test must be keyed to that run's own pids or process group, not a machine-wide pytest search (other projects run pytest and node test suites on this host concurrently). The fix belongs at the two pytest call sites (publish.py G4 and step 3), not in the shared run() helper, which every publish command uses.

## Step 1 measurements

2026-10-07: repro (20 sleeping tests plus a self-SIGKILL test, -n 4 loadgroup, repo flags) hung past a 120 s hard timeout without the flag (exit 124); with --max-worker-restart=0 it exited 1 in 17 s. The old subprocess.run timeout path left the pytest controller orphaned. Fix: commit a420ccfa.
