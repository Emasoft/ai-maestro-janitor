---
trdd-id: 3M5MDPPD
title: Owner question how a session finds PROJECT_MAP.md when CLAUDE.md never names it
column: backburner
status: tasked
created: 2026-11-15T12:20:38+0100
updated: 2026-11-15T12:20:38+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-15T12:20:38+0100
parent-trdd: FADYLSQB
---

# Owner question how a session finds PROJECT_MAP.md when CLAUDE.md never names it

## Question for the owner

Owner order 2026-11-15 (verbatim on TRDD-FADYLSQB): the map lives in a root PROJECT_MAP.md and CLAUDE.md must not reference it. How then does a session find PROJECT_MAP.md?

## Options (inferred, untested)

1. A path-scoped rule under .claude/rules with `paths` frontmatter.
2. A SessionStart hook line naming the file (a fixed per-session cost, resent every turn, no cache invalidation of CLAUDE.md).
3. Nothing; agents find it with ls or tldr.

## Docs fact

Per earlier research: a bare @path outside code spans imports a file; a plain mention does not load it.

## Status

Awaiting the owner's choice.

## Approval log

- 2026-11-15T12:20:38+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
