---
trdd-id: 8FYNVBWL
title: Hand the 3-pillars rules, detectors and hook over to the 3-pillars plugin
column: backburner
status: tasked
created: 2026-11-04T00:00:42+0100
updated: 2026-11-04T00:04:15+0100
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
approval-datetime: 2026-11-04T00:00:42+0100
---

# Hand the 3-pillars rules, detectors and hook over to the 3-pillars plugin

## User directive (verbatim, 2026-11-03, given to the 3-pillars-tasks-management session and repeated to this session)

> this plugin is being developed to replace the scattered 3-pillars rules that were scattered between 3 different plugins (ai-maestro project scope, ai-maestro-plugin and ai-maestro-janitor). so you must move all the rules, skills and hooks/agents (if any) here, in this plugin. no more things left in other plugins that are related to the 3-pillars-rules. this plugin will be then installed at user scope, and all agents will have full access to the rules, the skills and the 4 tools of the 3-pillars system. in addition to a mod that we are going to create soon that will display the kanban board of the whole fleet.

## Janitor side

- Starts only after the 3-pillars plugin is published on the Emasoft emasoft-plugins marketplace and installed at user scope (USER ruling 3, 2026-10-21). Until then the janitor keeps shipping its copies unchanged.
- Drop rules/prrd-design-rules.md, rules/trdd-design-tasks.md, rules/universal-kanban.md and rules/references/prrd-design-rules-full.md, trdd-design-tasks-full.md, universal-kanban-3p300-columns.md.
- Drop the detectors scripts/detectors/trdd-drift.py, trdd-reminder.py, trdd-state-reconciliation.py, trdd-cross-card-blindspot.py, report-to-trdd-drift.py and the hook scripts/hooks/on-session-start-trdd-state.py, with their tests and registrations, once the 3-pillars plugin ships their replacements.
- scripts/lib/rules_installer.py: stop installing those files, and never overwrite or remove a rules file whose provenance marker is not the janitor's.
- Janitor code that stays and reads cards (dispatch.py _blocked_reason, tests/test_secret_shield_wiring_gate.py) moves off scripts/lib/trdd_common.py onto the global trddgrep the 3-pillars plugin installs at user scope (trddgrep --porcelain). USER ruling 2026-11-04, verbatim: "the trddgrep as all the other tools must migrate in the 3-pillars plugin now. it will install them at user scope (in the path or symlinked in bin)  when it will be installed, so they will be available globallly. what it needs me for? ask the claude of the 3-pillars plugin with sendmessage instead."
- The moved detector must keep: the fixes of TRDD-OEEH2W28, the hold test from 842a8835, and the blocked-by DONE_COLUMNS hold that TRDD-2V7OAUPE relies on.
- The 3-pillars session sends the final file list and the installer hand-over before anything is removed.

## Found during

- Cross-session messages from the 3-pillars-tasks-management session, 2026-11-03, during TRDD-M1218EMH.

## Approval log

- 2026-11-04T00:00:42+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Provisional contract with the 3-pillars session (pending USER review of the 3-pillars migration plan)

- Marker: a rules file containing 3-pillars-tasks-management:installed-rule is not the janitor's; release N never overwrites or removes it.
- Stand-down: while the plugin named 3-pillars-tasks-management (from any marketplace) is enabled in any enabledPlugins scope, the five TRDD detectors and on-session-start-trdd-state.py stand down (release N). Expected marketplace emasoft-plugins, not verified until it is published.
- Order: janitor release N, then the 3-pillars publish and user-scope install, then janitor release N+1. Nothing is published on either side without the owner's word, and release N is not built before the owner approves the migration plan.
- CI: once the gate test calls trddgrep, it fails loudly when trddgrep is missing, and the janitor CI installs the 3-pillars plugin's trddgrep (not the copy in ai-maestro).
- Open, settled by the plan: where the references install; how the 3-pillars installer takes over a janitor-stamped file once without ping-pong with janitor sessions older than release N; what version= in the 3-pillars marker means; cleanup when the 3-pillars plugin is uninstalled.
