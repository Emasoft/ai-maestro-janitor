---
trdd-id: KLT5F93P
title: Memory pages live directly in the memory folder with no wikimem subfolder
column: todo
status: tasked
created: 2026-10-23T16:10:31+0200
updated: 2026-10-23T16:12:35+0200
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
approval-datetime: 2026-10-23T16:10:31+0200
---

# Memory pages live directly in the memory folder with no wikimem subfolder

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-23

OWNER MESSAGES, verbatim except that the home path and username are redacted to ~ and USER, 2026-10-23: (1) "lets consolidate the wikimem to use the same folder of claude code memories for local scoped memories. this will help now that we are changing the 3-pillars system to use the projects slugs to store the design documents too when the trdd or specs/prrd are local scoped." Pasted example in the same message: LOCAL memory ~/.claude/projects/-Users-USER-ai-maestro/memory and LOCAL design ~/.claude/projects/-Users-USER-ai-maestro/design. (2) "so avoid using the wikimem subfolder from now on. all memories goes into memory. No more ~/.claude/projects/-Users-USER-ai-maestro/memory/wikimem Instead only: ~/.claude/projects/-Users-USER-ai-maestro/memory". Our reading: these take priority over the board-drain mandate (TRDD-S6GX1DHN) for this work.

ALREADY TRUE: LOCAL wikimem pages already resolve to ~/.claude/projects/<slug>/memory/ (scripts/lib/memory_scopes.py:308; memgrep DEFAULT_LOCAL_SCOPE_PATTERN), the folder Claude Code's own memories use.

PART A, flatten the wikimem subfolder into its memory folder (janitor-only; nothing written yet). Measured: memgrep production code is folder-agnostic (scope_root_for walks up to the memory folder); ai-maestro reads nothing under the subfolder; 31 pages to move with no name collisions (LOCAL ai-maestro 24, LOCAL janitor under the ~/Code slug 1, USER plugin DATA 3, USER mirror 3); PROJECT-scope subfolders also exist in ai-maestro (1 page), CLAUDE-PLUGIN-VALIDATION (7), emasoft-complete-ios-app-authoring (1), git-tracked there, so ask each repo's session to move its own. Our reading, pending the owner (it reverses TRDD-ab232dbd, an owner ruling): harvest STOPS mirroring buffer notes (its CREATE writes a same-name curated copy, which in a flat folder would overwrite the harness note); harness notes and wikimem pages coexist in the memory folder, chores tell them apart by frontmatter, never by folder, and never mutate a harness note (build on memory_content_precheck's existing curated/raw predicate; expect a burst of findings on harness notes on the first pass after the move). This reverses the coexistence layout of TRDD-ab232dbd per owner message (2). Order: release the code change first (3.8.13 harvest would recreate the subfolder), then move pages only (leave each .memgrep sidecar, reindex and validate each scope), flatten the USER mirror in the same step (its sync is additive and a restore would recreate the subfolder), and drop the WIKI_SUBDIR check from memory_scopes._dir_has_memory. Consumers: memory_scopes.py (WIKI_SUBDIR, resolve_wiki_dir, _dir_has_memory), harvest SKILL.md and harvest-background.md, janitor-memory-bootstrap, janitor-memory-write and its examples, janitor-handoff-and-clear, tests (test_memory_scopes.py:264-265 and fixtures), write_gate.rs test fixtures, rules and memory pages that describe the subfolder.

PART B moved to its own card, TRDD-M5BRPISQ (blocked).

RISK and the launch-path question for part B: see TRDD-M5BRPISQ.

OPEN, OWNER: the canonical launch path (asked on TRDD-M5BRPISQ). It blocks this card only for this repo's LOCAL memory folder, which already exists under both the ~/Code and the /Volumes slug.

NEXT ACTION: write part A's code change through a worker now, except this repo's LOCAL folder under the ~/Code slug; do not move pages before the release; afterwards decide whether each emptied wikimem folder (with its stale .memgrep) moves to .trashcan.

## Approval log

- 2026-10-23T16:10:31+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
