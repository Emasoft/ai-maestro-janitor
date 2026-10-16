---
trdd-id: 9ORKPQCX
title: Janitor-typed slash commands may mint the owner's consent tokens
column: todo
status: tasked
created: 2026-10-16T22:29:03+0200
updated: 2026-10-16T22:29:03+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: security
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-16T22:29:03+0200
---

# Janitor-typed slash commands may mint the owner's consent tokens

Found by the round-2 review of TRDD-0TSG80CL's consent guard (2026-10-16). The janitor's own triggers type commands into the pane: clear_trigger types /clear or /janitor-handoff-and-clear, reload_trigger types /reload-plugins, resume_trigger types /janitor-resume. If the UserPromptSubmit hook sees janitor-typed pane input as an ordinary prompt and a typed command is in user_intent._VERB_COMMANDS, the machine mints a consent token for its own action, the same forged-consent class as the /goal case (TRDD-B3PY3HV7). Unverified: whether the hook sees typed pane input as a prompt, which typed commands match _VERB_COMMANDS, and whether any consumer (disarm_guard.authority, global_control_cli._authorized, terminal_trigger's injection_allowed calls near lines 2357 and 2363) reads a token minted that way before it expires. reload_trigger.py:176 and clear_trigger.py:87 now hold only comments, not injection_allowed calls. First step: measure, read-only, then propose.

## Approval log

- 2026-10-16T22:29:03+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
