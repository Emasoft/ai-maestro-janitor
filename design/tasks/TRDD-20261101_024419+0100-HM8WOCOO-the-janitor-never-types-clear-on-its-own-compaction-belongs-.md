---
trdd-id: HM8WOCOO
title: the janitor never types clear on its own, compaction belongs to the user's compaction mod
column: dev
status: tasked
created: 2026-11-01T02:44:19+0100
updated: 2026-11-01T02:44:19+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-01T02:44:19+0100
---

# the janitor never types clear on its own, compaction belongs to the user's compaction mod

USER 2026-11-01 verbatim: "i have installed a mod for the compaction, you don't need to send clear anymore. update the -lugin with these two things and publish asap and install".

Every automatic /clear funnels through scripts/clear_trigger.py::spawn_shrink_chain (dispatch idle-clear, on-stop-token-meter Stop-boundary clear incl. its past-ceiling branch, reload_trigger and reload_skills_trigger shrink-first). Gate it at the top on a new userConfig option auto_clear_enabled (default false) returning (False, reason); every caller already falls back (reloads proceed without the shrink). clear_trigger.main() (the manual /janitor-handoff-and-clear path) does not call spawn_shrink_chain, so manual use is unaffected. The pre-tool-context-usage nudges stop telling the model to run /janitor-compact-context. Out of scope: the /compact senders (cold-cache compact on resume, 85% enforcement, proactive idle compact) — still on, reported to the user.

## Approval log

- 2026-11-01T02:44:19+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
