---
trdd-id: KLT5F93P
title: Memory pages live directly in memory and LOCAL design moves to the project slug folder
column: todo
status: tasked
created: 2026-10-23T16:10:31+0200
updated: 2026-10-23T16:10:31+0200
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

# Memory pages live directly in memory and LOCAL design moves to the project slug folder

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-23

OWNER MESSAGES, verbatim except that the home path and username are redacted to ~ and USER, 2026-10-23: (1) "lets consolidate the wikimem to use the same folder of claude code memories for local scoped memories. this will help now that we are changing the 3-pillars system to use the projects slugs to store the design documents too when the trdd or specs/prrd are local scoped." Pasted example in the same message: LOCAL memory ~/.claude/projects/-Users-USER-ai-maestro/memory and LOCAL design ~/.claude/projects/-Users-USER-ai-maestro/design. (2) "so avoid using the wikimem subfolder from now on. all memories goes into memory. No more ~/.claude/projects/-Users-USER-ai-maestro/memory/wikimem Instead only: ~/.claude/projects/-Users-USER-ai-maestro/memory". These override the board-drain mandate (TRDD-S6GX1DHN) for this work.

ALREADY TRUE: LOCAL wikimem pages already resolve to ~/.claude/projects/<slug>/memory/ (scripts/lib/memory_scopes.py:308; memgrep DEFAULT_LOCAL_SCOPE_PATTERN), the folder Claude Code's own memories use.

PART A, flatten the wikimem subfolder into its memory folder (janitor-only; nothing written yet). Measured: memgrep production code is folder-agnostic (scope_root_for walks up to the memory folder); ai-maestro reads nothing under the subfolder; 31 pages to move with no name collisions (LOCAL ai-maestro 24, LOCAL janitor under the ~/Code slug 1, USER plugin DATA 3, USER mirror 3); PROJECT-scope subfolders also exist in ai-maestro (1 page), CLAUDE-PLUGIN-VALIDATION (7), emasoft-complete-ios-app-authoring (1), git-tracked there, so ask each repo's session to move its own. Design decided after review: harvest STOPS mirroring buffer notes (its CREATE writes a same-name curated copy, which in a flat folder would overwrite the harness note); harness notes and wikimem pages coexist in the memory folder, chores tell them apart by frontmatter, never by folder, and never mutate a harness note. This reverses the coexistence layout of TRDD-ab232dbd per owner message (2). Order: release the code change first (3.8.13 harvest would recreate the subfolder), then move pages only (leave each .memgrep sidecar, reindex and validate each scope), flatten the USER mirror in the same step (its sync is additive and a restore would recreate the subfolder), and drop the WIKI_SUBDIR check from memory_scopes._dir_has_memory. Consumers: memory_scopes.py (WIKI_SUBDIR, resolve_wiki_dir, _dir_has_memory), harvest SKILL.md and harvest-background.md, janitor-memory-bootstrap, janitor-memory-write and its examples, janitor-handoff-and-clear, tests (test_memory_scopes.py:264-265 and fixtures), write_gate.rs test fixtures, rules and memory pages that describe the subfolder.

PART B, LOCAL design to ~/.claude/projects/<slug>/design/ (BLOCKED). Measured: one resolver per repo (janitor trdd_common.local_design_root; ai-maestro lib/pillar/kinds.ts:367); 28 cards in 10 in-tree .claude/local/design dirs fleet-wide; 9 leftover slug design dirs from before TRDD-WY198OIP hold 31 cards, mostly under ~/Code slugs, one with a refused/ folder. Order: (1) release a janitor version retiring the in-tree migration in scripts/hooks/on-session-start-trdd-state.py (it moves slug cards into the tree each SessionStart) and wait until every armed session has restarted off the old hook; (2) ai-maestro switches its resolver, with the slug computed from the main checkout root, no realpath, every non-alphanumeric byte replaced by '-'; (3) janitor switches local_design_root to that slug, plus rules, footprint, tests, and a detector for leftover in-tree dirs and for slug design dirs whose project path no longer exists; (4) per-project migration after a per-project trdd-id collision check; leftover refused/ cards get column: refused and move to proposals/. Check whether specgrep and prrdgrep resolve LOCAL through the same kinds.ts path. Design keys on the main checkout (cards must survive a worktree); memory keys on the launch path (Claude Code dictates it), so they can differ.

RISK, INFERRED from the resolve_local_design_mirror_dir docstring (memory_scopes.py:668), not measured: Claude Code's cleanupPeriodDays sweep covers ~/.claude/projects/<slug>/ and 2.1.228 exempted the memory folder but not design/, so LOCAL design cards there could be deleted by the sweep; verify before step 3.

OPEN, OWNER: which launch path is canonical for projects under the external volume, /Volumes/EmaUITEK4TBSSD/Code/... or ~/Code/... (a symlink to it)? Claude Code keys transcripts and MEMORY.md on the launch path, so sessions must always start from the chosen one or two LOCAL corpora return; everything under the other slug merges into it. Blocks part B and part A's single janitor LOCAL page.

NEXT ACTION: write part A's code change through a worker after the owner sees this card; do not move pages before the release.

## Approval log

- 2026-10-23T16:10:31+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
