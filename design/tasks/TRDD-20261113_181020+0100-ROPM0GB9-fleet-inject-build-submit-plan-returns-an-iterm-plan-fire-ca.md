---
trdd-id: ROPM0GB9
title: fleet_inject build_submit_plan returns an iTerm plan fire cannot run
column: todo
status: tasked
created: 2026-11-13T18:10:20+0100
updated: 2026-11-13T18:13:10+0100
current-owner: main-agent@ai-maestro-janitor
created-by: user
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: user
approval-datetime: 2026-11-13T18:10:20+0100
---

# fleet_inject build_submit_plan returns an iTerm plan fire cannot run

Found by the TRDD-RJJGXPIK recovery worker, then confirmed by reading the code at commit 36c0b945. In scripts/lib/fleet_inject.py, build_submit_plan returns {channel, steps, delay_s, command} with no `osascript` key. fire() then reads plan['osascript'] for the iTerm channel, which raises KeyError (fire()'s only except clause is `except (OSError, subprocess.SubprocessError)`, read at 36c0b945, so the KeyError propagates). This is the Enter-alone step that pane_actuate.build_step_plan uses after a queue flush, so an iTerm recovery rung that needs a separate Enter crashes instead of submitting. Not yet reproduced at runtime. Fix: give the iTerm submit plan its osascript, the way the TRDD-RJJGXPIK change's fleet_inject._readback_split_plan helper does, and add a test proving that fire() accepts an iTerm submit plan.

## Approval log

- 2026-11-13T18:10:20+0100 — MANDATE issued by user (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-13 — correction: created by the orchestrator session from a worker finding; the user did not issue this mandate or approve it. trddgrep new recorded the user because --author is required.
- 2026-11-13 — clarification: approved: true and approval-judge in the frontmatter were written by trddgrep new; outside the ai-maestro harness the session itself is the approver, so read them as the session's approval, not the user's.

## Links

Related: TRDD-RJJGXPIK (source of the finding).
