---
trdd-id: FADYLSQB
title: Concise project map back in CLAUDE.md under the G7.1 and G10.1 fence
column: todo
status: tasked
created: 2026-11-15T01:12:06+0100
updated: 2026-11-15T01:12:06+0100
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
approval-datetime: 2026-11-15T01:12:06+0100
---

# Concise project map back in CLAUDE.md under the G7.1 and G10.1 fence

## STATE

NEXT ACTION: measure first: the token size of the old map (removed 2026-08-14, about 46,000 tokens per turn; generator scripts/lib/repomap/, switch /janitor-auto-repomap-on, archived TRDD-E247A349), then design a concise map with a measured token budget, then propose (PROPOSAL FOR ACTION marker), build, and only if the concise map meets the budget, put it in the project-map fence golden rules G7.1 and G10.1 require and amend the CLAUDE.md section "Navigating this codebase — use tldr, never a static map".
Queued 2026-11-15 behind TRDD-F8EIVTSG increment 3 (TRDD-QAF3N673), whose research worker is running.

## Owner directive (verbatim, 2026-11-15)

"no, the project map is important. it was a little too big for the context, so i asked you to make a more concise version of the map. if you succeed, you can amend the block from CLAUDE.md"

## Context

Golden rules G7.1 and G10.1 require a project-map fence in CLAUDE.md; CLAUDE.md currently forbids a static map because the old one cost about 46,000 tokens per turn. The owner keeps the rules and wants the map back, concise. Success criterion: a measured per-turn token cost the owner would accept (state the number in the proposal), generated, kept current without churning the tracked file (the same problem as #328), and useful for navigation.

## Approval log

- 2026-11-15T01:12:06+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
