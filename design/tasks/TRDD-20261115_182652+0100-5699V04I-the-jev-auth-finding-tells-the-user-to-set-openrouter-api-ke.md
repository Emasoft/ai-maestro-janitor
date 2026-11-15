---
trdd-id: 5699V04I
title: The Jev auth finding tells the user to set OPENROUTER_API_KEY when llm-ext reports a key or credits failure
column: todo
status: tasked
created: 2026-11-15T18:26:52+0100
updated: 2026-11-15T18:26:52+0100
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
approval-datetime: 2026-11-15T18:26:52+0100
---

# The Jev auth finding tells the user to set OPENROUTER_API_KEY when llm-ext reports a key or credits failure

Since 84ad09ba (TRDD-7XDBJZCZ) an llm-ext exit 3 (key or credits) raises JevAuthError with no HTTP status. The lane's auth finding (scripts/lib/jev_compaction_lane.py, the provider-auth message builder that emits 'provider key rejected: {reason} — set OPENROUTER_API_KEY / CLAUDE_PLUGIN_OPTION_JEV_PROVIDER' when status is not 401/402/403) then names the direct-path remedy, while on the llm-ext route the key lives in the llm-ext profile and an out-of-credits run is reported as a bad key. llm-ext's own message (with its 'Fix:' line) is embedded as {reason}. TO DO: give the llm-ext route its own remedy wording (name the llm-ext profile and point at the embedded llm-ext message), keyed on the error coming from score_items_via_llm_ext rather than on a parsed status. Acceptance: a test that an exit-3 llm-ext failure yields a finding whose remedy does not name OPENROUTER_API_KEY.

## Approval log

- 2026-11-15T18:26:52+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
