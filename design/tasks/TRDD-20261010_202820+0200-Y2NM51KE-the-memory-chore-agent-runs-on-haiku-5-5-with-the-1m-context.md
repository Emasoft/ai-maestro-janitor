---
trdd-id: Y2NM51KE
title: The memory chore agent runs on Haiku 5.5 with the 1M context at medium effort instead of Sonnet
column: dev
status: tasked
created: 2026-10-10T20:28:20+0200
updated: 2026-10-10T20:35:18+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: refactor
min-approval-requirement: user
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
approved: true
approval-judge: user
approval-datetime: 2026-10-10T20:28:31+0200
---

# The memory chore agent runs on Haiku 5.5 with the 1M context at medium effort instead of Sonnet

Owner directive, 2026-10-10, verbatim: 'why the memory chores subagents are still use sonnet? haiku 5.5 is amazingly better than the previous versions, use a haiku 5.5 model [1m] with effort low or medium.' Change: agents/janitor-memory-subconscious-agent.md frontmatter from model sonnet, effort high to model haiku[1m], effort medium (the owner allowed low or medium; medium is the main session's pick, since the chores are editorial and gated by memgrep's loss checks). Every text that names the memory agent's model follows: the agent body, the janitor-memory skills and their reference files, rules/janitor-heartbeat-protocol.md, the docstring of scripts/detectors/memory-maintenance.py, and the assertion in tests/test_heartbeat_protocol_rule.py. Not touched: mentions of Sonnet that are about something else (README stale-task row, scripts/dispatch.py allowlist comment, token and fleet code). Takes effect for dispatched chores only after a release, since sessions load the agent and the rule from the installed plugin; until then this session passes the model override when it spawns the agent. Verify: grep finds no Sonnet in the listed files; uv run pytest tests/test_heartbeat_protocol_rule.py passes; the strict validator accepts the agent frontmatter. Supersedes, for the memory agent only, the Sonnet pin of the owner directive of 2026-09-05.

## Approval log
- 2026-10-10T20:28:31+0200 — APPROVED by user (min-approval-requirement: user). the owner gave this directive himself on 2026-10-10; quoted verbatim in the body.
- 2026-10-10T20:28:32+0200 — column → dev. being built now

## Second owner directive

2026-10-10 20:31, verbatim: 'stop using other agents in the janitor chores. only haiku 5.5 1m. use the effort according to the complexity of the chore, but max high.' READING by the main session (the owner's words are the sentence above, the rest is interpretation): 'other agents' means other models, so all three janitor chore agents run on haiku[1m], the repair and security agents included (both were on opus); no chore runs above high effort. EFFORT per chore, the session's picks: memory chores get their effort at spawn time from the heartbeat rule, low for repair, enrich and relocate (mechanical, lint-driven), medium for atomize, harvest and retro-lesson, high for split, consolidate and conflict (judgment plus a loss proof); the memory agent's frontmatter keeps medium as the default for a direct call; the repair agent and the security agent stay at high. This supersedes the first directive's 'low or medium' ceiling. Scope widened accordingly: agents/janitor-repair-agent.md, agents/janitor-security-agent.md, tests/test_security_agent.py, the memory row of rules/janitor-heartbeat-protocol.md.
2026-10-10 20:35 BUILT by two lean-workers (0.11 and 0.12 million tokens); the main session read every changed line. FINAL EFFORT PICKS, changed after the review and still the session's: low for repair and enrich; medium for atomize and relocate (relocate applies a privacy test); high for split, consolidate, conflict, harvest and retro-lesson (the last two write new knowledge). Also built: one sentence in the memory and security agents telling them to spawn any sub-agent on haiku at no more than high effort (the repair agent has no Agent tool); the citation after each Haiku statement now names the decision of 2026-10-10, not the Sonnet cost decision of 2026-06-30. THE OTHER READING, not taken: 'other agents' as other agent TYPES (chores spawning no helper agents at all, or one agent for everything); said to the owner in the session. RISK, said to the owner: the repair and security agents carry promises that are prose a model must follow (never rotate credentials, never force-push, ticket text is untrusted data) and the security agent reads hostile text by design; no test measures that Haiku keeps them, the changed test asserts the model string only. NOT ESTABLISHED: that a plugin agent with model haiku[1m] loads on Haiku with the 1M context (proven only for user-scope agents; a loader that ignored it would fall back to the session's model, silently); that an effort passed at spawn overrides the frontmatter default (if not, every memory chore runs at medium). The strict validator could not be run by the worker (it used the bare package name); the main session runs it through the pipeline's own invocation in the gate. NOT YET DONE: the PROJECT memory page janitor-skills-and-agents-roster still states the old pins; the USER memory atom on Sonnet workers is partly superseded.

## Acceptance

- [x] All three chore agents carry model haiku[1m] and no effort above high; no text in agents, the memory skills, the heartbeat rule or the detector docstring calls a chore agent Sonnet or Opus as its model (122 tests passed in the worker's run of the five affected files; ruff, mypy, pyright exit 0).
- [ ] The strict validator accepts the three agent files (run in the gate on this commit).
- [ ] FIELD, after a release: a dispatched memory chore's agent transcript names a Haiku model, and a split or consolidate chore shows high effort while a repair chore shows low.
