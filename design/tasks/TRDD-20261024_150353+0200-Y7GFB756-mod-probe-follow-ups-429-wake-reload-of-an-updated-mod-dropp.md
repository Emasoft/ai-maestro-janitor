---
trdd-id: Y7GFB756
title: Mod probe follow-ups - 429 wake, reload of an updated mod, dropping prompts, post-clear bootstrap
column: backburner
status: tasked
created: 2026-10-24T15:03:53+0200
updated: 2026-10-24T15:03:53+0200
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
approval-datetime: 2026-10-24T15:03:53+0200
---

# Mod probe follow-ups - 429 wake, reload of an updated mod, dropping prompts, post-clear bootstrap

Follow-ups left open by TRDD-M7RALXUW (closed 2026-10-24; evidence in reports/mods-feasibility/20261024_145813+0200-mods-probes.md, gitignored).

1. Does $.prompt.submit wake a session after a 429 or usage wall? Only when one occurs naturally; never provoke one.
2. Does /reload-plugins (typed or via $.command.run) re-import an installed mod whose cached version changed?
3. Can a mod drop a scheduled-trigger prompt or a peer hand-back in prompt.submit, so that no model turn is spent?
4. Post-clear bootstrap: after $.command.run('clear'), session.start did not fire again and $.state resets. Can the mod re-arm and resume from session.end (reason clear), or from the resolution of the clear call, followed by $.prompt.submit?
5. Does $.command.run work after a user Esc, when $.prompt.submit is dropped?

Same method as M7RALXUW: a throwaway mod, a separate process outside the repo, the janitor and context-harness disabled for that process.

## Approval log

- 2026-10-24T15:03:53+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
