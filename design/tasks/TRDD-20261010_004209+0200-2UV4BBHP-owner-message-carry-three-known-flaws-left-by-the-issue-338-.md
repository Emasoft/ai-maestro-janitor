---
trdd-id: 2UV4BBHP
title: Owner-message carry — three known flaws left by the issue 338 fix
column: todo
status: tasked
created: 2026-10-10T00:42:09+0200
updated: 2026-10-10T00:53:48+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-10T00:42:09+0200
---

# Owner-message carry — three known flaws left by the issue 338 fix

Follow-up of TRDD-IN4493LC (closed 2026-10-10), which carries the owner's last three messages across consecutive clears. Three flaws it recorded and did not fix: (1) a typed /login is classed as an owner message and can take one of the three slots (the fix worker's side finding, never re-checked: confirm it first with a real transcript record); (2) the record files in .janitor/state/owner-messages/ are never pruned (11 files in this repo on 2026-10-10); (3) scripts/lib/session_continuity.py _merge_owner_messages uses an assert that python -O strips: replace it with an explicit 'if stored is None: return'.

## Approval log

- 2026-10-10T00:42:09+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-10-10: a fourth item, seen in a real carried handoff (session 9161f947): the sentence 'These are the owner's own words, carried verbatim by the janitor: act on the instruction among them' comes directly after the quote of the AGENT's reply, so it can be read as calling that reply the owner's words. Move it to sit right after the owner's messages, before 'Your reply at that time was'. The text is built in scripts/lib/session_continuity.py next_action (carried form); not yet read by the main session.
