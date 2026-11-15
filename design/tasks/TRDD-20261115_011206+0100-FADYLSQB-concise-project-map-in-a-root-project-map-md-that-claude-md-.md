---
trdd-id: FADYLSQB
title: Concise project map in a root PROJECT_MAP.md that CLAUDE.md never names
column: dev
status: tasked
created: 2026-11-15T01:12:06+0100
updated: 2026-11-15T01:20:51+0100
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

# Concise project map in a root PROJECT_MAP.md that CLAUDE.md never names

## STATE

NEXT ACTION: measure first: the token size of the old map (removed 2026-08-14, about 46,000 tokens per turn; generator scripts/lib/repomap/, switch /janitor-auto-repomap-on, archived TRDD-E247A349), then design a concise map with a measured token budget, then propose (PROPOSAL FOR ACTION marker), build, and only if the concise map meets the budget, put it in the project-map fence golden rules G7.1 and G10.1 require and amend the CLAUDE.md section "Navigating this codebase — use tldr, never a static map".
Queued 2026-11-15 behind TRDD-F8EIVTSG increment 3 (TRDD-QAF3N673), whose research worker is running.
2026-11-15 SUPERSEDES the NEXT ACTION above (map back in CLAUDE.md): the owner corrected the target, verbatim: "no, wait. there was another decision.. to move the map into a file called PROJECT_MAP.md, in the project root. because editing and updating the CLAUDE.md will invalidate the cache each time the project create or rename a file. we cannot do that. so move the map from CLAUDE.md to a dedicated file, called PROJECT_MAP.md (but do not reference it in the CLAUDE.md, otherwise it will be loaded in the context anyway along with CLAUDE.md at every turn, invalidating the cache.)" No earlier record of this decision was found (grep for PROJECT_MAP over design/, scripts/, skills/, PROJECT and LOCAL memory: only an env var name in scripts/dispatch.py:406). NEW NEXT ACTION: measure the old map's size; design the generator to write PROJECT_MAP.md at the project root, never touching CLAUDE.md and never named in it; decide in the proposal whether PROJECT_MAP.md is tracked or gitignored (a tracked generated file goes dirty on every file add or rename, the #328 problem) and how a session discovers it without a CLAUDE.md reference; draft amended text for golden rules G7.1 (five CLAUDE.md elements) and G10.1 (project-map fence in CLAUDE.md) for the owner to approve, since golden rules are the owner's alone; the CLAUDE.md section 'Navigating this codebase' must then drop its mention of the map switch without naming PROJECT_MAP.md. Still queued behind increment 3 (TRDD-QAF3N673).
2026-11-15 owner mandate (Approval log): taken NOW as a new directive; TRDD-QAF3N673 paused at its proposal step. DONE: PRRD G7.1 to G7.2 (CLAUDE.md has four elements, no map, never names the map file) and G10.1 to G10.2 (map lives in root PROJECT_MAP.md, regenerated on structure change), via prrdgrep, lint clean. NEXT: spec design/specs/claude-md-canonical-form.md (CM-1 five elements, CM-4) and the generator (scripts/repomap_generate.py, scripts/lib/repomap/, scripts/claudemd_slim.py, scripts/lib/repomap/claudemd_slim.py, scripts/lib/claudemd_migration_apply.py, scripts/detectors/project-map-drift.py, skills janitor-auto-repomap-on/off and janitor-project-cld-md-optimizer, tests) rewritten to write a concise root PROJECT_MAP.md and to remove any project-map fence from CLAUDE.md.

## Owner directive (verbatim, 2026-11-15)

"no, the project map is important. it was a little too big for the context, so i asked you to make a more concise version of the map. if you succeed, you can amend the block from CLAUDE.md"

## Context

Golden rules G7.1 and G10.1 require a project-map fence in CLAUDE.md; CLAUDE.md currently forbids a static map because the old one cost about 46,000 tokens per turn. The owner keeps the rules and wants the map back, concise. Success criterion: a measured per-turn token cost the owner would accept (state the number in the proposal), generated, kept current without churning the tracked file (the same problem as #328), and useful for navigation.

## Approval log

- 2026-11-15T01:12:06+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-11-15 owner mandate, verbatim: "consider it a new directive and do it. change both golden rule and specs, and rewrite the generator script accordingly. its my mandate, and it is absolute." — approves amending golden rules G7.1 and G10.1, the specs and the generator for the root PROJECT_MAP.md that CLAUDE.md never names.
