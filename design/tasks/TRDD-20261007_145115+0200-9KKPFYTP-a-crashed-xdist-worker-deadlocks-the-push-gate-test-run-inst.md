---
trdd-id: 9KKPFYTP
title: A crashed xdist worker deadlocks the push gate test run instead of failing it
column: todo
status: tasked
created: 2026-10-07T14:51:15+0200
updated: 2026-10-07T14:56:36+0200
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
---

# A crashed xdist worker deadlocks the push gate test run instead of failing it

Observed 2026-10-07 during the 3.8.7 publish. The pre-push hook re-runs the full pytest suite with xdist and -x. At 99% one worker (gw6) crashed with 'node down: Not properly terminated' while host load was over 100. The run then deadlocked from 13:43: stack samples showed the controller waiting to read from its workers and every worker waiting to read from the controller, all at 0% CPU, and a replacement worker idle. The per-test 300 s timeout cannot break it because no test is running. It was ended by stopping the controller, the push was refused, and the rerun later passed. The same suite passed twice that day under the same flags, so the crash is most likely a load flake; the bug is the hang.

Investigate: installed pytest-xdist is 3.8.0 (checked 2026-10-07). Whether --max-worker-restart=0 makes a crash fail the run cleanly, and an outer wall-clock limit on the hook's test run.

Acceptance: a worker crash fails the gate within a bounded time, proven by a real test that kills a worker.

## Approval log

- 2026-10-07T14:51:15+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-10-07T14:56:30+0200: the gate runs `uv run --extra dev pytest tests/ -x -q --tb=short -n auto --dist loadgroup --timeout=300 --timeout-method=thread` (scripts/publish.py _PYTEST_CMD, line 225); the pre-push hook is git-hooks/pre-push (line 48 runs `uv run python scripts/publish.py --gate`). The only outer wall-clock limit on the hook's pytest run is _TEST_SUITE_TIMEOUT_SEC = 3600 s (scripts/publish.py:185, applied at :1475 and :1733); the hook itself has no timeout. It did not end the 13:43 hang because the run was stopped by hand before 3600 s elapsed (stop time not recorded, so this is inferred). The crashed test was not identified, because the log did not name it. The acceptance test must run the deadlock scenario in a child pytest process with its own hard timeout, so a regression cannot deadlock the suite that runs it.
