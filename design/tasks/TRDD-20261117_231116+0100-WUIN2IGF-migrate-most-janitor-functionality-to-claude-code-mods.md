---
trdd-id: WUIN2IGF
title: Migrate most janitor functionality to Claude Code mods
column: backburner
status: tasked
created: 2026-11-17T23:11:16+0100
updated: 2026-11-17T23:11:16+0100
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
approval-datetime: 2026-11-17T23:11:16+0100
---

# Migrate most janitor functionality to Claude Code mods

Owner 2026-11-17 (verbatim): "convert those issues into TRDDs to solve all those issues and improve the whole janitor system migrating to mods most of its functionalities. but those TRDDs must be written now and handled later."

## Goal
Improve the whole janitor by moving most of its functionality out of the cron heartbeat, the dispatcher stub and the terminal-typing clear chain, and into Claude Code mods, where hooks and panes run inside the harness without keystrokes or a session-scoped cron. Several open issues (the clear chain, the goal re-send, heartbeat noise in the agent conversation) involve that outside-in design; that this design is their cause is a hypothesis for the inventory to test, not a finding.

## First step, inventory only
Classify each item below as: move to a mod hooks module, move to a mod pane or band, or stay as is, with the reason for each.
- the hooks in hooks/hooks.json;
- the heartbeat detectors in scripts/detectors/ (about 80);
- the skills in skills/ (about 65);
- the status and token meters (janitor-show-global-status, janitor-token-report, janitor-token-attribution).

## Known state
- The secret shield in hooks/secret-shield/ is already a mod, not yet wired (TRDD-2V7OAUPE).
- Prior mod cards: TRDD-M7RALXUW (probe of what a mod can do, complete), TRDD-R9NLNV3W (liveness mod), TRDD-I6FUQ4SD (daemon reader for mod-liveness state files and pruning of ended session files), TRDD-8FYNVBWL (hand the 3-pillars rules, detectors and hook over to the 3-pillars plugin).
- Mod terms: read the skill mods-expert-developer-plugin:mods-doc-mods-overview before the inventory.

## Done means
The inventory table is written, each row has a decision and a reason, and one follow-up card per move exists. This card does no migration itself.

Owner 2026-11-17: written now, handled later; the secrets-shield scanner (TRDD-BAQB9SYO) has priority.

## Approval log

- 2026-11-17T23:11:16+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
