---
trdd-id: 79728HXT
title: Test suite writes the real plugin-data global-state notify-sent.txt
column: cancelled
status: archived
created: 2026-10-21T20:59:26+0200
updated: 2026-10-21T21:04:09+0200
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
approval-datetime: 2026-10-21T20:59:26+0200
---

# Test suite writes the real plugin-data global-state notify-sent.txt

SUSPECTED, not proven (2026-10-21, while planning TRDD-1J9B7MWO): the real plugin-data global-state/notify-sent.txt changed during a full uv run pytest run, but the live janitor daemon writes that file legitimately, so the evidence does not separate a suite leak from a daemon write. FIRST STEP: tell the two apart (run the suite with the daemon stopped and compare the file's mtime and content before and after, or identify the writing process). If the daemon wrote it, cancel this card and drop it from TRDD-1J9B7MWO's npt. If the suite leaked, fix: find the test(s) and the code path that resolve the notify-sent path without the test isolation override, route them through the isolated global-state dir, and add a guard test that the suite leaves the real file untouched (snapshot mtime and content before and after). Prerequisite (npt) of TRDD-1J9B7MWO, whose new tests depend on this store.

## Approval log

- 2026-10-21T20:59:26+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-21T21:04:09+0200 — CANCELLED by main-agent@ai-maestro-janitor. premise false: the suite is isolated; only the live daemon writes notify-sent.txt.

## Outcome (2026-10-21)

No leak. Static: scripts/lib/notify.py resolves gs.global_state_dir()/notify-sent.txt; global_state_dir() gives $JANITOR_GLOBAL_STATE_DIR absolute priority, and tests/conftest.py sets it to a per-session temp dir plus a before/after manifest guard of the real dirs; no real_state-marked test mentions notify (grep 2026-10-21). Empirical: the notify, rotator_alert and login_needed tests (113 passed) left the real file's sha1 and mtime unchanged. The live daemon is the only writer. Report: docs_dev/20261021-79728HXT-notify-sent-writer.md (gitignored).
