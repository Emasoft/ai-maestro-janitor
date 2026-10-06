---
trdd-id: 8H00AA9F
title: spawned janitor memory agent has empty CLAUDE_PLUGIN_ROOT and runs 3.7.0 scripts
column: backburner
status: tasked
created: 2026-10-06T20:03:46+0200
updated: 2026-10-06T20:03:46+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T20:03:46+0200
---

# spawned janitor memory agent has empty CLAUDE_PLUGIN_ROOT and runs 3.7.0 scripts

Symptom: in a spawned janitor memory agent's shell CLAUDE_PLUGIN_ROOT was empty, and the agent fell back to the 3.7.0 plugin cache path while 3.7.5 was installed, so it ran old scripts. Cause: NOT diagnosed; possibly the session loaded the skill from the 3.7.0 base directory. Evidence: the memory agent's own observation on 2026-10-06; not yet reproduced. Acceptance: reproduce in a fresh spawned memory agent and record whether CLAUDE_PLUGIN_ROOT is set and which version path the skill base directory names; then either fix the path resolution so the newest installed version is used or record why the 3.7.0 path was legitimate.

## Approval log

- 2026-10-06T20:03:46+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
