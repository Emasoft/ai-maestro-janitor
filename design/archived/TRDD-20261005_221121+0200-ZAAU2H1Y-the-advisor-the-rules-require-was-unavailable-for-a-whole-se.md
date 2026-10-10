---
trdd-id: ZAAU2H1Y
title: The advisor the rules require was unavailable for a whole session
column: complete
status: archived
created: 2026-10-05T22:11:21+0200
updated: 2026-10-10T20:07:05+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:11:21+0200
---

# The advisor the rules require was unavailable for a whole session

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Five multi-file changes on 2026-10-05 went ahead with no advisor verdict because the agent type was not offered to the session. Find why it was absent.

## Approval log

- 2026-10-05T22:11:21+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T20:07:05+0200 — COMPLETE by main-agent@ai-maestro-janitor. present cause read; nothing to build here.

## Corrections

2026-10-05 (review): the count of five multi-file changes was not made; two code commits touched more than one file.
2026-10-10 20:06. CAUSE FOUND for today's state, by reading: the user settings file carries the fable-advisor plugin with the value false, so the plugin is installed in the cache but disabled, and its agent type is not offered to any session; this session's agent list does not contain it. What IS offered today is a built-in advisor tool, which the rule names as the first choice, so the rule can be met (it was called in the sessions of 2026-10-10). NOT SHOWN: that the plugin was already disabled on 2026-10-05, or whether the built-in tool was offered that day; the setting's change date was not read. Nothing to build in this repository: the setting is the owner's (owner item 20). NARROWING: closed on the present cause, the 2026-10-05 session itself was not examined.

## Acceptance

- [x] Why the advisor agent type was absent is found for today's state (the plugin is disabled in the user settings); NARROWED: the 2026-10-05 session itself was not examined, nothing built.
