---
trdd-id: TEP6F3A3
title: Secret-shield checks before wiring the mod
column: design
status: tasked
created: 2026-11-03T22:42:41+0100
updated: 2026-11-03T22:46:29+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-03T22:42:41+0100
---

# Secret-shield checks before wiring the mod

## Questions to answer before hooks/hooks.json gains a modules key
- Does a Claude Code older than 2.1.287 reject the whole hooks/hooks.json when it carries a modules key, so the janitor's classic hooks stop too?
- In which order do the mod's tool.call rewrite and the janitor's Python PostToolUse updatedToolOutput run, and does one undo the other?
- Does a CLAUDE_PLUGIN_OPTION_SECRET_SHIELD_* value in the settings env block reach the mod's options? Probe with a project settings file in the probe repo. If it does not, add a Python warning when the env block sets one, since it would have no effect.
- What does the user type: /janitor-secret-shield, or a plugin-prefixed name? Check the command list in a live session.
How to test a Claude Code older than 2.1.287 when none is installed; if it cannot be tested, declare a minimum Claude Code version instead.
Does CPV --strict accept a modules key in hooks/hooks.json?
Disabling jr-redact belongs to the wiring card, not here.
## Done when
Each question has a measured answer recorded here, and the option descriptions and the usage text match it.
Found during TRDD-M1218EMH.

## Approval log

- 2026-11-03T22:42:41+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
