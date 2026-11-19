---
trdd-id: DSXC9MP9
title: Secret-shield mod keeps every secret behind a vault UUID the agent never sees, resolved by the shield CLI in commands
column: backburner
status: tasked
created: 2026-11-18T17:47:37+0100
updated: 2026-11-18T23:58:11+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-18T17:47:37+0100
---

# Secret-shield mod keeps every secret behind a vault UUID the agent never sees, resolved by the shield CLI in commands

## Approval log

- 2026-11-18T17:47:37+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-18 — main-agent@ai-maestro-janitor confirms it ordered this card and is its author of record; the cheap-worker that minted it used that author on the main agent's instruction.

## Owner orders

2026-11-18 (verbatim): its not only prompt scanning. the current mod for example (its called jr-redact btw) scans and redact all tools outputs from secrets before they reach the agent. the agent never see a single secret. but it is inefficient and poor compared to secrets-shield, since secrets-shield keep an unique uuid of each secret that can be used to handle the secret via scripts by read and write them using the sqlite db with few commands. the agent can use the secrets-shields to read, compare and verify skills without ever see them. it execute the secrets-shield cli tool and any bash command can get the secret as argument just by adding the tool with the uuid in the right place, and it will be resolved to the secret, like a env var. And even if the agent scan the launch arguments via ps of the processes, the secrets-shield will always redact the output of everything, so it will only see the uuid of the secret listed along the processes launch string, never the secret. so the agent can write and even code with secrets, without worting about them, since they will never be seen by it or sent to the transcript jsonl of the sessions. this is why the janitor-secrets-shield is much better than the jr-redact mod currently installed. secrets are not lost, they are simply stored in an invisible way. How to do this is something that you must leave to the mods-expert-developer agent, but the directives that you must give to it are these. be sure to remember these words of mine.
2026-11-18 (verbatim): "you forgot that i told you that the secrets-shield must not only scan and redact the context and the jsonl transcripts in realtime, preventing agents to ever read or send via api a secret (like the installed mod partially does, but it is incomplete) but also to prevent committing secrets with executing the secrets-scanner on the committed files at each commit? before that git cliff will create the changelog (otherwise there is the risk of publishing secrets in the very release logs of github, or metadata of npm, bun or pypi packages!)? What are you doing now? implement those immediately. secrets-shield must be blazing fast (with its performance critical core routines optimized in rust) and always on when the janitor is armed!"
2026-11-18 (owner message on the shield): jss CLI, autonomous .env editing and a context field per secret. Verbatim text and derived requirements R1-R4 in design/specs/TRDD-DSXC9MP9-owner-jss-envkey.md.
2026-11-18, main-agent reading (not the owner's words): the jss name replaces `shield get` in the mods-expert design, and the context field is a new column of the vault row. Derived requirements R1-R4 are in design/specs/TRDD-DSXC9MP9-owner-jss-envkey.md.
2026-11-18 (owner message on the shield): jss add NAME VALUE "CONTEXT" writes a secret straight into the vault; the owner's envget helper for .env is the example. Verbatim text, derived requirements R5-R7 and four open questions in design/specs/TRDD-DSXC9MP9-owner-jss-add.md.
2026-11-18 (owner message on the shield): the owner added tested .env helpers for jss in scripts/janitor-env-tools/, copied to design/requirements/examples/janitor-env-tools/; PRRD G27.1-G33.1 now hold the owner's secrets-shield orders verbatim.

## Owner

Design and implementation belong to the mods-expert-developer agent (owner order 2026-11-18). Related: TRDD-QM8YRCZ5, TRDD-J4CBUB41, TRDD-51IDZ4DB, TRDD-FNPDFZWU, TRDD-BAQB9SYO.
