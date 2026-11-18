---
trdd-id: NZYFCUDN
title: handoff_clear_verify runs a command named by an undeclared plugin option that a repo can set
column: backburner
status: tasked
created: 2026-11-18T14:48:21+0100
updated: 2026-11-18T14:48:21+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: security
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-18T14:48:21+0100
---

# handoff_clear_verify runs a command named by an undeclared plugin option that a repo can set

Found 2026-11-18 by main-agent during TRDD-SWQXCIOS: scripts/handoff_clear_verify.py _context_tokens (line ~589) reads CLAUDE_PLUGIN_OPTION_HANDOFF_VERIFY_CONTEXT_COMMAND from the environment (default 'agentlenspro get_burn_status'), splits it on spaces and runs it with subprocess.run, no shell. The option is not declared in .claude-plugin/plugin.json, so it is not a user setting the plugin knows about: any process environment can set it, including the env block of a cloned repository's .claude/settings.json, so a repository can choose the command the janitor runs. The risk is close to project hooks, which also need workspace trust, but this path is undocumented. Fix to decide: declare the option in plugin.json userConfig and read it only from there, or drop the configurable command and call the fixed agentlenspro probe with a resolved absolute path. Test: with the env var set to a sentinel command, the sentinel never runs unless the option is set through the declared user setting.
Links: parent context TRDD-SWQXCIOS (bandit sweep).

## Approval log

- 2026-11-18T14:48:21+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
