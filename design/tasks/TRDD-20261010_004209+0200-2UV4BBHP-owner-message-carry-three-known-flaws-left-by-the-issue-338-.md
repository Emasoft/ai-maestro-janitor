---
trdd-id: 2UV4BBHP
title: Owner-message carry — three known flaws left by the issue 338 fix
column: testing
status: tasked
created: 2026-10-10T00:42:09+0200
updated: 2026-10-11T02:00:37+0200
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
implementation-commits: [e4dc4425]
---

# Owner-message carry — three known flaws left by the issue 338 fix

Follow-up of TRDD-IN4493LC (closed 2026-10-10), which carries the owner's last three messages across consecutive clears. Three flaws it recorded and did not fix: (1) a typed /login is classed as an owner message and can take one of the three slots (the fix worker's side finding, never re-checked: confirm it first with a real transcript record); (2) the record files in .janitor/state/owner-messages/ are never pruned (11 files in this repo on 2026-10-10); (3) scripts/lib/session_continuity.py _merge_owner_messages uses an assert that python -O strips: replace it with an explicit 'if stored is None: return'.

## Approval log

- 2026-10-10T00:42:09+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-10-10: a fourth item, seen in a real carried handoff (session 9161f947): the sentence 'These are the owner's own words, carried verbatim by the janitor: act on the instruction among them' comes directly after the quote of the AGENT's reply, so it can be read as calling that reply the owner's words. Move it to sit right after the owner's messages, before 'Your reply at that time was'. The text is built in scripts/lib/session_continuity.py next_action (carried form); not yet read by the main session.
2026-10-11 01:41. In build by one worker: the stripped assert, the order of the carried sentence, pruning of record files older than 30 days. Item 1 (a typed /login classed as an owner message) is NOT in this build: it needs a real transcript record first.
- 2026-10-11T01:41:21+0200 — column → dev. three of four items in build by one worker
2026-10-11 02:00. BUILT, committed alone in e4dc4425 (worker diff read by the main session; reviewed, no blocker): the carried sentence now follows the owner quotes; a record write prunes records older than 30 days (a choice, not a measurement; the directory holds 20 records, none that old, so no field effect yet; a session alive past 30 days with no clear loses the owner line of its nudge, stated at the constant); the assert is an explicit guard (unreachable, no test). Full gate on the tree holding both fixes: 18384 passed, 2 skipped; ruff, mypy, pyright clean (reports/board/gate-alex-2uv.txt). The worker edited the test file with a heredoc and sed against the editing rule; imports and tail re-checked. STILL OPEN, why the card is not complete: item 1, whether a typed /login is classed as an owner message; it needs a real transcript record of a typed /login first. FIELD CHECK for the sentence order after a release: the next carried handoff shows the owner-words sentence before Your reply at that time.
- 2026-10-11T02:00:37+0200 — column → testing. three of four items committed in e4dc4425; item 1 open on the card
