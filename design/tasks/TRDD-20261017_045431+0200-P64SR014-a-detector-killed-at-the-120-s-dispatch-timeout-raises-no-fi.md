---
trdd-id: P64SR014
title: A detector killed at the 120 s dispatch timeout raises no finding
column: backburner
status: tasked
created: 2026-10-17T04:54:31+0200
updated: 2026-10-17T04:56:00+0200
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

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-17

Scope: all three silent outcomes share the gap: error:timeout (dispatch.py:1316-1334), error:spawn-failed (1337) and error:rc=N (1351) all go through _record_default_outcome with no finding. Absence checked 2026-10-17 across scripts, skills, commands, hooks and agents (all file types) for 'last-outcome', 'error:timeout', and glob forms 'outcome*' / 'last-outcome*': the only hits are the writers (dispatch.py, state.py, guard/branch_protection_apply.py). Column backburner, deliberately: 0 last-outcome stamps in this project carry error:, so no detector has been observed killed or crashed in the field; move to todo on the first real one.
CORRECTION to the archived TRDD-XRT9LOQL DECISION line (that card is archived and immutable, so it lives here): its claim that the fallback is blind only when the walk overruns the 120 s kill while skip-with-log is blind on every timeout overstates the fallback. Measured: git ls-files 3.51 s cold at 500k untracked files on the external volume, the walk 4 to 10 times slower, so file count does not cause the timeout. A volume-caused timeout (slow, contended or waking disk, git lock) would probably also kill the walk, and a kill is as silent as a skip. Keeping the fallback is the default (no code churn), not a measured advantage. Not measured: contended or cold-disk conditions. The folder/* caveat was not reproduced with a big/* layout; a layout that forces descent was not tried.
