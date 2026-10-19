---
trdd-id: 5ID9CQY8
title: The clear chain bootstrap types only the resume command because the cron survives a clear
column: todo
status: tasked
created: 2026-10-18T04:39:02+0200
updated: 2026-10-19T23:20:13+0200
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
- 2026-10-18 08:10 clear (Jev compaction, session 77e6aba3 to 33ef3d73): the re-arm's CronDelete of the prior heartbeat id 590dbe30 SUCCEEDED ('Cancelled job 590dbe30.'), so that cron survived this /clear too; handoff_clear_verify.py again reported it as 'destroyed by /clear, recreated by re-arm' (reports/continuity-build/20261018_081056+0200-handoff-clear-verify.md). Second observation after the 03:44 one; box 1 asks for at least two more beyond 03:44, so one more is owed.
2026-10-19 23:15 — WORK ITEM box 4 LANDED (commit aeb41b33): scripts/handoff_clear_verify.py now extracts the re-arm's successful CronDelete of the prior heartbeat id from the transcript (requires tool_use_id pairing with a CronDelete tool_use whose input.id equals the prior id, plus the result-text match 'Cancelled job <id>') and stores the matched id as prior_cron_deleted in the after-snapshot; compute_verdicts reports 'SURVIVED the clear' only when the matched id equals b_id, neutral otherwise — a surviving cron is no longer mislabelled 'destroyed by /clear, recreated by re-arm'. Module docstring reworded to the conditional classification. New negative test (input.id mismatch → guard-off) added; three adversarial review rounds, final APPROVE no blocking findings; both round-2 MINOR items closed. Gate green: pytest 65 + 46 consumer tests, ruff/mypy/pyright clean. Worker report: reports_dev/20261019_204500+0200-5id9cqy8-box4-handoff-clear-verify.md (ai-maestro#168).

## Acceptance

- [ ] Confirm on at least two more clears that the prior heartbeat cron is still listed after `/clear` (CronList before the bootstrap), or drop this card if it is ever gone.
- [ ] The clear chain types only `/janitor-resume`; every reload trigger that composes on `BOOTSTRAP_CMDS` still re-arms (it must keep `/janitor-arm` or compose its own). After this change a session whose cron DID die at a clear depends on the SessionStart heartbeat self-check and the armed.flag re-plumb; a test or a log line must show that backstop fires.
- [ ] A dry-run keystroke-plan test for the clear chain and for each reload trigger fails before and passes after.
- [x] `handoff_clear_verify.py` no longer reports a surviving cron as destroyed.
- [ ] Full gate green (ruff, mypy, pyright, pytest).

## Approval log

- 2026-10-18T04:39:02+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
