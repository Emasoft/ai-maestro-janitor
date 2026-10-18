---
trdd-id: 5ID9CQY8
title: The clear chain bootstrap types only the resume command because the cron survives a clear
column: todo
status: tasked
created: 2026-10-18T04:39:02+0200
updated: 2026-10-18T04:39:24+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: refactor
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-18T04:39:02+0200
parent-trdd: K9AHY1ZB
derived: true
---

# The clear chain bootstrap types only the resume command because the cron survives a clear

## What

Item C5 of TRDD-K9AHY1ZB Release 2, never built and never carded until 2026-10-18: the clear chain's bootstrap becomes `(RESUME_CMD,)` because crons survive `/clear`; the reload triggers keep `/janitor-arm`.

## Measured 2026-10-18

- `scripts/clear_trigger.py:82` still reads `_BOOTSTRAP_CMDS: tuple[str, ...] = (ARM_CMD, RESUME_CMD)`, exported as `BOOTSTRAP_CMDS` for other triggers via `spawn_shrink_chain`. No commit names C5.
- Evidence that a cron survives `/clear`: after the 2026-10-18 03:44 janitor clear, the re-arm's `CronDelete` of the prior heartbeat id 19df26ee SUCCEEDED ("Cancelled job 19df26ee"), so that cron still existed after the clear. `scripts/handoff_clear_verify.py` labelled the same id change "destroyed by /clear, recreated by re-arm", which the successful delete contradicts. That success is evidence because CronDelete fails not-found for an id that no longer exists (the janitor-arm skill relies on exactly that), and the id cannot have been re-created: the SessionStart self-check only re-plumbs when no heartbeat exists and would store a new id. One observation only, on Claude Code 2.1.302; a later Claude Code version re-opens the question.

## Acceptance

- [ ] Confirm on at least two more clears that the prior heartbeat cron is still listed after `/clear` (CronList before the bootstrap), or drop this card if it is ever gone.
- [ ] The clear chain types only `/janitor-resume`; every reload trigger that composes on `BOOTSTRAP_CMDS` still re-arms (it must keep `/janitor-arm` or compose its own). After this change a session whose cron DID die at a clear depends on the SessionStart heartbeat self-check and the armed.flag re-plumb; a test or a log line must show that backstop fires.
- [ ] A dry-run keystroke-plan test for the clear chain and for each reload trigger fails before and passes after.
- [ ] `handoff_clear_verify.py` no longer reports a surviving cron as destroyed.
- [ ] Full gate green (ruff, mypy, pyright, pytest).

## Approval log

- 2026-10-18T04:39:02+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
