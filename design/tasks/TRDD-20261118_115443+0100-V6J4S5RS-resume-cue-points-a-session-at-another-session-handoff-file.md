---
trdd-id: V6J4S5RS
title: Resume cue points a session at another session handoff file
column: backburner
status: tasked
created: 2026-11-18T11:54:43+0100
updated: 2026-11-18T11:54:43+0100
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
approval-datetime: 2026-11-18T11:54:43+0100
---

# Resume cue points a session at another session handoff file

Observed 2026-11-18 by main-agent in session 5d861615 (after a compaction, not a clear): the heartbeat dispatcher stub printed a [janitor-resume] cue whose next line said: a fuller summary of the cleared session is at .janitor/state/agent-handoff-e05195b8-20261118_113415+0100-5194.md, read it FIRST, it supersedes the auto-composed template you resumed from. That file was written by the external watcher for a different session (e05195b8, idle about 298 h, working on TRDD-MIMC57XX), not for 5d861615. A session that obeyed the cue would have reconciled its plan with another session's work. Expected: the cue names only a handoff written for the current session id, or names none. To check: which resume phase in scripts/dispatch.py emits the fuller-summary line, and how it picks the handoff file (newest in the project vs. matching the session id). Not yet traced; no code read for this card.

## Approval log

- 2026-11-18T11:54:43+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
