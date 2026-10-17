---
trdd-id: P64SR014
title: A detector killed at the 120 s dispatch timeout raises no finding
column: backburner
status: tasked
created: 2026-10-17T04:54:31+0200
updated: 2026-10-17T04:54:31+0200
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
approval-datetime: 2026-10-17T04:54:31+0200
---

# A detector killed at the 120 s dispatch timeout raises no finding

Fact, verified: when a detector exceeds CLAUDE_PLUGIN_OPTION_DETECTOR_TIMEOUT (default 120 s, scripts/dispatch.py:1301), dispatch kills it. It then only writes a log line (detector '<name>' timed out after Ns -- killed), prints any partial output, and stamps last-outcome-<name>.ts with error:timeout plus the cadence stamp (dispatch.py:1316-1334). Nothing turns error:timeout into a finding the owner sees: the only reader of last-outcome stamps is dispatch's own _record_default_outcome (dispatch.py:1252).

Why it matters: a chronically killed security detector reads as healthy. TRDD-XRT9LOQL kept the git-listing fallback walk, which on a slow volume would likely be killed at 120 s, so that blindness would be silent.

Fix idea: raise a deduped finding when a detector's outcome is error:timeout (or error:rc) on N consecutive fires. Optionally, bound the own_files fallback walk by the remaining budget and raise a finding when it aborts.

Cites: TRDD-XRT9LOQL.

## Approval log

- 2026-10-17T04:54:31+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
