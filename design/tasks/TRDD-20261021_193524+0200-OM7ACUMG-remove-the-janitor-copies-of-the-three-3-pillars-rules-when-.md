---
trdd-id: OM7ACUMG
title: Remove the janitor copies of the three 3-pillars rules when 3-pillars-tasks-management ships them
column: backburner
status: tasked
created: 2026-10-21T19:35:24+0200
updated: 2026-10-21T20:58:50+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: refactor
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-21T19:35:24+0200
release-via: publish

eht: [WBDGJS2Y]
---

# Remove the janitor copies of the three 3-pillars rules when 3-pillars-tasks-management ships them

Agreed with the ai-maestro session (TRDD-7KY62GNB, message 2026-10-21): the janitor keeps shipping trdd-design-tasks.md, prrd-design-rules.md and universal-kanban.md until the 3-pillars-tasks-management plugin releases its replacement. At that release the ai-maestro session sends the plugin name, its version, the exact skill and rule names it owns, and the filename of its always-loaded pointer rule (installed by a SessionStart installer like our rules_installer).

Work when that message arrives, in ONE janitor release: stop installing the three rules; make sure our installer never removes or overwrites the new plugin's pointer rule (the two installers must not race on one filename); re-point janitor-footprint.md and the three-pillars-rules-ownership memory page to the new owner.

Blocked on: the handover message from the ai-maestro session. Not actionable before it.

## Approval log

- 2026-10-21T19:35:24+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Also in the removal release

The rule copies the janitor already wrote to ~/.claude/rules/ (trdd-design-tasks.md, prrd-design-rules.md, universal-kanban.md) must not stay loaded next to the new plugin's skill and pointer rule. Decide whether the release moves them out (they are outside the project tree, so safe-delete refuses them: ask the user, or retire them through whatever mechanism rules_installer already has for managed rule files; check that first) and never leave both loaded. Update the tests that assert the installer ships these three rules in the same release.
