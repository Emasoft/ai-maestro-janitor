---
trdd-id: VZT4MY0T
title: Remove the janitor's own compaction chores and commands, replaced by context-harness
column: backburner
status: tasked
created: 2026-10-23T08:56:08+0200
updated: 2026-10-23T08:56:08+0200
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
approval-datetime: 2026-10-23T08:56:08+0200
---

# Remove the janitor's own compaction chores and commands, replaced by context-harness

OWNER, 2026-10-23 (verbatim): "ok, you can remove all janitor chore and commands relative to compacting." Then: "this is the plugin that replaced the janitor compaction: https://github.com/ysys143/context-harness" (its Jev backend is being moved to OpenRouter on the Emasoft fork, branch feat/openrouter-jev-provider, session context-harness-call-jev). CORE SCOPE (unambiguous): the skills janitor-compact-context, janitor-handoff-and-clear and janitor-write-handoff; the jevctx compaction engine under scripts/lib/jevctx; the daemon's cold-cache clear and compact chores; the external /clear trigger; the post-clear compaction SessionStart hook; their tests and docs. OPEN OWNER QUESTION (asked, not answered): whether to also remove (a) the post-compact auto-resume (PostCompact hook, the [janitor-resume] heartbeat cue, the orphaned-resume-flag detector), (b) the PreCompact handoff snapshot, (c) the context-usage and token-spike warnings in PreToolUse, (d) the cold-cache clear on SessionStart. Note: auto-resume and the PreCompact snapshot also serve Claude Code's own auto-compact, which context-harness does not replace. Method: inventory with tldr references / impact plus a grep sweep of non-code (rules, skills, README, hooks.json, settings), remove dead code in its own commit first, sweep every reference category, full gate. Removal is large (about 3 skills, 5 hooks, 35 scripts, 40 test files): plan before code.

## Approval log

- 2026-10-23T08:56:08+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
