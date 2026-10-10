---
trdd-id: 7H8YH57W
title: A test in test_dispatch_phases writes to the real plugin data usage-probe folder
column: cancelled
status: archived
created: 2026-10-07T09:36:02+0200
updated: 2026-10-10T22:26:27+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T09:36:02+0200
---

# A test in test_dispatch_phases writes to the real plugin data usage-probe folder

Observed 2026-10-07 during batch B8: running tests/test_dispatch_phases.py printed "[plugin-data] CHANGED ... usage-probe/*.json", so a test touches the real plugin DATA dir. Find the test, isolate it to a tmp dir, add a guard.

## Approval log

- 2026-10-07T09:36:02+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T22:26:27+0200 — CANCELLED by main-agent@ai-maestro-janitor. not a defect: the quoted line is the write-guard reporting the live daemon's own writes.

## Findings

2026-10-10 22:26 NOT A DEFECT, closed without code. The line the card quotes, '[plugin-data] CHANGED ... usage-probe/...', is printed by the suite's own write-guard at session end (tests/conftest.py, the block that builds daemon_diffs, about lines 1040 to 1070): it re-snapshots the real plugin data dir and, when a live janitor daemon is proven to have ticked during the run, reports the changes under the heading 'attributed to a LIVE janitor actor ... not a test leak'. The usage-probe folder is written by the running daemon's rotator (cooldown and lock files; scripts/lib/usage_probe.py line 154 resolves it under the home directory), and the daemon was running (pid 6931 today, under launchd). The card read the informational list as a test write. CHECKED today: uv run pytest tests/test_dispatch_phases.py gives 229 passed and prints no such line; the module's env_isolation fixture sets HOME to a temp dir (line 55), so usage_probe's folder resolves inside the temp tree for every test that uses it. NOT CHECKED: that every test in that file uses the fixture, and the write sandbox's own coverage of this path was read only as far as its comment (conftest lines 343 to 372).
