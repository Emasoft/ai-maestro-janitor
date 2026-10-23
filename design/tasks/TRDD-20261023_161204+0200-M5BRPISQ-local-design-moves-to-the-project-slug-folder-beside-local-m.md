---
trdd-id: M5BRPISQ
title: LOCAL design moves to the project slug folder beside LOCAL memory
column: backburner
status: tasked
created: 2026-10-23T16:12:04+0200
updated: 2026-10-23T16:16:27+0200
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
approval-datetime: 2026-10-23T16:12:04+0200
blocked-by: []
unblock-when: []
pre-block-column: 
blocker-probe: []
blocker-holds-if: 
---

# LOCAL design moves to the project slug folder beside LOCAL memory

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-23

Split from TRDD-KLT5F93P (part B there); the owner's two messages of 2026-10-23 are quoted on that card. Owner's ask for this card, from message (1): LOCAL design at ~/.claude/projects/<slug>/design, beside the LOCAL memory.

MEASURED: one resolver per repo (janitor scripts/lib/trdd_common.py local_design_root; ai-maestro lib/pillar/kinds.ts:367); 28 cards in 10 in-tree .claude/local/design dirs fleet-wide; 9 leftover slug design dirs from before TRDD-WY198OIP hold 31 cards, mostly under ~/Code slugs, one with a refused/ folder. This repo's LOCAL memory is already split across two slug folders (the ~/Code one and the /Volumes one), because Claude Code keys the folder on the launch path.

ORDER (our reading of the reviews, not an owner ruling): (1) release a janitor version that retires the in-tree migration in scripts/hooks/on-session-start-trdd-state.py (it moves slug cards into the tree each SessionStart), then wait until every armed session has restarted off the old hook; (2) ai-maestro switches its resolver, with the slug computed from the main checkout root, no realpath, every non-alphanumeric byte replaced by '-'; tell them by cross-session message (not GitHub) and warn them that trdd-create's id-collision check (their TRDD-7KY62GNB item a) becomes correct again and must not be "fixed" the other way first; (3) janitor switches local_design_root to that slug, plus rules, footprint, tests on a scratch HOME (never the real ~/.claude/projects), and a detector for leftover in-tree dirs and for slug design dirs whose project path no longer exists; (4) per-project migration after a per-project trdd-id collision check; leftover refused/ cards get column: refused and move to proposals/. Check whether specgrep and prrdgrep resolve LOCAL through the same kinds.ts path. Proposed rule, pending the owner: design keys on the main checkout (cards must survive a worktree), memory keys on the launch path (Claude Code dictates it), so they can differ.

RISK, INFERRED from the resolve_local_design_mirror_dir docstring (scripts/lib/memory_scopes.py:668), not measured: Claude Code's cleanupPeriodDays sweep covers ~/.claude/projects/<slug>/ and 2.1.228 exempted the memory folder but not design/; verify before step 3.

PARKED in backburner (no card blocks it, so blocked would be false, and todo would claim it can be pulled; step 1 could possibly share a release with TRDD-KLT5F93P, which is itself on hold): waits on the owner's answer to which launch path is canonical for projects under the external volume, /Volumes/EmaUITEK4TBSSD/Code/... or ~/Code/... (a symlink to it); sessions must then always start from it, or two LOCAL corpora return. Also on ai-maestro's resolver change.

## Approval log

- 2026-10-23T16:12:04+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
