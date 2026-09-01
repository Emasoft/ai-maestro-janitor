---
trdd-id: 0HRRZO8S
title: Use the ai-maestro harness's startup-argument power — the new env vars and settings worth setting fleet-wide
column: backburner
created: 2026-09-01T19:26:25+0200
updated: 2026-09-02T00:58:00+0200
current-owner: janitor-main-session
task-type: feature
scope: project
project-id: ai-maestro-janitor
severity: medium
min-approval-requirement: user
blocked-by: []
npt: []
eht: []
relevant-rules: []
external-refs: [TRDD-DD5X4O6Z]
---

# The janitor can shape how claude is LAUNCHED — the new levers worth pulling

## Why (USER directive, 2026-09-01)

*"In the ai-maestro harness, the janitor can even change the startup arguments used to launch
the claude code executable. Those powers must be used."* Recent releases added launch-time
levers that materially serve the janitor's goals (cache economy, continuity, containment):

| Lever | Since | What it buys |
|---|---|---|
| `promptCacheTtl` / `subagentPromptCacheTtl` settings | 2.1.243 | pin a 1-hour main-conversation cache where the account type honors it — the single biggest cache-economy knob |
| `experimental.cacheTtl` agent frontmatter | 2.1.248 | per-agent cache TTL for long-lived workers (lean-worker etc.) |
| `ANTHROPIC_DEFAULT_MODEL` | 2.1.236 | start fleet sessions on the intended model without the hard pin of `ANTHROPIC_MODEL` (a `/model` pick still wins) |
| `CLAUDE_CODE_RETRY_WATCHDOG` | ≤2.1.239 | persistent retry for unattended sessions; now fails fast on spend-limit/out-of-credits |
| `--restricted` / `CLAUDE_CODE_RESTRICTED=1` | 2.1.248 | a contained profile for read-only worker launches |
| `CLAUDE_CODE_PROJECT_DIR_NAME` | 2.1.234 | short per-project transcript dir names for per-session config dirs |
| `CLAUDE_CODE_SUBAGENT_MODEL` (semantics changed) | 2.1.251 | now a DEFAULT, not an override — re-check any harness use of it |
| `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` | 2.1.257 | forces the subagent model over per-spawn `model:` and agent-definition overrides — pins a whole fleet's workers to sonnet[1m] (workflows-rules) without editing every agent file; pair with the 2.1.251 DEFAULT semantics above (TRDD-NUD3DGX5 item 3) |

## Scope

1. For each lever: decide applies/does-not-apply for this fleet (subscription vs API-key
   matters for `promptCacheTtl` — VERIFY it is honored on this account type before claiming
   savings), and where it lands (harness launch args vs settings.json vs agent frontmatter).
2. The janitor side ships settings/frontmatter it owns; harness-launcher changes are
   PROPOSED to the ai-maestro project through its own tracker, never edited from here
   (`how-to-fix-issues-of-other-projects`).
3. USER approval required: fleet-wide launch changes affect every session on the machine.

## Acceptance

- [ ] per-lever decision table with the verification evidence (not changelog prose)
- [ ] janitor-owned pieces landed; harness pieces filed on ai-maestro with links back here
- [ ] USER signed off before anything fleet-wide takes effect

## Notes and lessons learned

*(none yet)*
