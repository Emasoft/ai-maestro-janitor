---
trdd-id: HM8WOCOO
title: the janitor never types clear on its own, compaction belongs to the user's compaction mod
column: dev
status: tasked
created: 2026-11-01T02:44:19+0100
updated: 2026-11-01T02:54:25+0100
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

## Correction 2026-11-01

The body's claim that every automatic /clear funnels through spawn_shrink_chain is FALSE: external_clear.enabled() separately gates the daemon _fire path (external_handoff_clear.py), cold_cache_clear_task.py and the on-session-start-cold-cache-clear hook, and this machine sets CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_ENABLED=true, so that path was live. auto_clear_enabled is therefore a MASTER switch: off makes both spawn_shrink_chain and external_clear.enabled() refuse, whatever the per-lever knobs say. The manual /janitor-compact-context goes through external_handoff_clear and is off with it; /janitor-handoff-and-clear (clear_trigger.main) stays manual. Whether these levers produced the /clear clear session title is inferred, not traced.
