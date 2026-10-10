---
trdd-id: JQLBZMMN
title: A memory agent spawned by the heartbeat finds CLAUDE_PLUGIN_ROOT empty and sets it by hand
column: verify_assumptions
status: tasked
created: 2026-10-10T08:17:30+0200
updated: 2026-10-10T08:58:30+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-10T08:17:30+0200
---

# A memory agent spawned by the heartbeat finds CLAUDE_PLUGIN_ROOT empty and sets it by hand

Seen once, 2026-10-10 07:34, reported by the consolidate agent the heartbeat marker dispatched in this project: CLAUDE_PLUGIN_ROOT was empty in its shell and it set the variable by hand to the 3.8.11 cache directory to run the claim and the close. Agent-reported, not observed by the main session. Every chore skill invokes its scripts through that variable, so an agent that guesses the directory can run a stale version's scripts. TO DO FIRST: reproduce by spawning the agent type and printing the variable; read how the skills and the agent definition resolve the plugin root; check whether a hand-set path to an older cached version is possible after an update. Acceptance: the agent resolves the plugin root without guessing, or the skills carry a resolver that fails loudly, with a test.

## Approval log

- 2026-10-10T08:17:30+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T08:41:40+0200 — column → verify_assumptions. agent-reported once; reproduce first
2026-10-10 08:58 CORRECTION to the body, filed here because the card has no other section: 'every chore skill invokes its scripts through that variable' was read for ONE skill only (the consolidate protocol's invocation example); 'an agent that guesses the directory can run a stale version' is a hypothesis, not an observation.
