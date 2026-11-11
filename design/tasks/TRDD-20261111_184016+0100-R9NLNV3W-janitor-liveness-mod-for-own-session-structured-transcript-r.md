---
trdd-id: R9NLNV3W
title: janitor liveness mod for own-session structured transcript reading
column: backburner
status: tasked
created: 2026-11-11T18:40:16+0100
updated: 2026-11-11T18:41:02+0100
current-owner: user
created-by: user
task-type: feature
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: user
mandate: true
mandated-by: none
approved: true
approval-judge: user
approval-datetime: 2026-11-11T18:40:16+0100
---

# janitor liveness mod for own-session structured transcript reading

## Approval log

- 2026-11-11T18:40:16+0100 — MANDATE issued by user (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## STATE

CURRENT (2026-11-11) — TRDD-B created, backburner. Owner directive: ONLY the mods-expert-developer agent may develop or review mods-related work. Mod watches its OWN session via session.append/turn.complete events + $.clock.every timer on $.session.messages() tail; reports liveness state (idle/working/api_error/retry_wedge) to daemon via state file, replacing the osascript/iTerm read path for the session it runs in. NO recovery actuation from the mod (its event loop is blocked when the session is frozen — review finding). Recovery stays external (TRDD-RJJGXPIK). $.command.run({command:'clear'}) probe needed. Delegation target: mods-expert-developer-plugin:mods-expert-developer-agent.
