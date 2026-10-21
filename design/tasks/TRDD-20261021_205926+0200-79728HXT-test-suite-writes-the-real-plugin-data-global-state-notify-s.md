---
trdd-id: 79728HXT
title: Test suite writes the real plugin-data global-state notify-sent.txt
column: todo
status: tasked
created: 2026-10-21T20:59:26+0200
updated: 2026-10-21T20:59:26+0200
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

Found 2026-10-21 while planning TRDD-1J9B7MWO: a full uv run pytest run wrote the REAL plugin-data global-state/notify-sent.txt instead of a temp dir, so a test run can suppress or alter a real desktop notification's dedupe. Fix: find the test(s) and the code path that resolve the notify-sent path without the test isolation override, route them through the isolated global-state dir, and add a guard test that the suite leaves the real file untouched (snapshot mtime and content before and after). Prerequisite (npt) of TRDD-1J9B7MWO, whose new tests depend on this store.

## Approval log

- 2026-10-21T20:59:26+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
