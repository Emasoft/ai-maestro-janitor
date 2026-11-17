---
trdd-id: M5BRPISQ
title: LOCAL design moves to the project slug folder beside LOCAL memory
column: backburner
status: tasked
created: 2026-10-23T16:12:04+0200
updated: 2026-11-17T23:13:13+0100
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
pre-block-column: backburner
blocker-probe: trddgrep --porcelain show KQULEGL2
blocker-holds-if: match:\t(backburner|approval|design|design_ai_review|design_human_review|todo|verify_assumptions|plan|dispatch|dev|testing|ai_review|human_review|blocked|failed|proposal|planned)\t
relevant-rules: [13, 14, 15, 24]
npt: [KQULEGL2]
blocker-probe-canary: match:KQULEGL2
---

# LOCAL design moves to the project slug folder beside LOCAL memory

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-23

Split from TRDD-KLT5F93P (part B there); the owner's two messages of 2026-10-23 are quoted on that card. Owner's ask for this card, from message (1): LOCAL design at ~/.claude/projects/<slug>/design, beside the LOCAL memory.

MEASURED: one resolver per repo (janitor scripts/lib/trdd_common.py local_design_root; ai-maestro lib/pillar/kinds.ts:367); 28 cards in 10 in-tree .claude/local/design dirs fleet-wide; 9 leftover slug design dirs from before TRDD-WY198OIP hold 31 cards, mostly under ~/Code slugs, one with a refused/ folder. This repo's LOCAL memory is already split across two slug folders (the ~/Code one and the /Volumes one), because Claude Code keys the folder on the launch path.

ORDER (our reading of the reviews, not an owner ruling): (1) release a janitor version that retires the in-tree migration in scripts/hooks/on-session-start-trdd-state.py (it moves slug cards into the tree each SessionStart), then wait until every armed session has restarted off the old hook; (2) ai-maestro switches its resolver, with the slug computed from the main checkout root, no realpath, every non-alphanumeric byte replaced by '-'; tell them by cross-session message (not GitHub) and warn them that trdd-create's id-collision check (their TRDD-7KY62GNB item a) becomes correct again and must not be "fixed" the other way first; (3) janitor switches local_design_root to that slug, plus rules, footprint, tests on a scratch HOME (never the real ~/.claude/projects), and a detector for leftover in-tree dirs and for slug design dirs whose project path no longer exists; (4) per-project migration after a per-project trdd-id collision check; leftover refused/ cards get column: refused and move to proposals/. Check whether specgrep and prrdgrep resolve LOCAL through the same kinds.ts path. Proposed rule, decided under G26 on measured facts unless choosing the main checkout contradicts golden G24 or G15, in which case it goes to the owner (see STATE): design keys on the main checkout (cards must survive a worktree), memory keys on the launch path (Claude Code dictates it), so they can differ.

RISK, INFERRED from the resolve_local_design_mirror_dir docstring (scripts/lib/memory_scopes.py:668), not measured: Claude Code's cleanupPeriodDays sweep covers ~/.claude/projects/<slug>/ and 2.1.228 exempted the memory folder but not design/; verify before step 3.

PARKED in backburner: its NPT TRDD-KQULEGL2 is complete (spec F22: Claude Code's cleanup never deletes a non-empty <slug>/design/; an empty one can be rmdir-ed, so the migration must leave at least one file in it; further obligations, subfolder names and a disappearance guard, are in the Approval log of 2026-10-24); the earlier blocker 78GMFJB4 (VERIFY-7) is complete and found that trddgrep has no input carrying the launch path (spec F20). This card owns which input step 2 adds; that is step 2's own work, not a gate. DECISION REQUIRED BEFORE STEP 3 (G26 on measured facts, unless choosing the main checkout contradicts golden G24 or G15, which would make it the owner's; first check whether those rules reach LOCAL design cards, since WL-5 marks the design extension as a D decision, not golden text): the proposed rule in the ORDER paragraph (design keys on the main checkout) conflicts with spec WL-5 (a worktree session writes its LOCAL cards to its own worktree slug); resolve and amend one of them. The current-layout worktree question was answered by TRDD-Q6UOJR8G (spec F21): trddgrep reaches LOCAL design only through an explicit --design-dir, from any checkout, so a caller that computes the slug folder can already pass it; whether that is enough is part of step 2. Step 1 could possibly share a release with TRDD-KLT5F93P, which is itself on hold. The launch-path question is ANSWERED (PRRD G24.1, 2026-10-23): the slug follows Claude Code's rule, the launch path as the session sees it, symlinks not resolved (observed 2026-10-23: this repo has one slug folder per launch path; not yet proven by launching once from each path, and this desktop-app session got the resolved form), so a project started from both /Volumes/EmaUITEK4TBSSD/Code/... and ~/Code/... gets two slug folders and two LOCAL design corpora, just as Claude Code gets two memory folders. Now waits on the spec design/specs/wikimem-layout-spec.md (WL-2, WL-5) and its VERIFY items, above all whether Claude Code's cleanup ever touches <slug>/design/ (measured: trddgrep has no launch-path input today, F20; adding one is step 2's work); and still on ai-maestro's resolver (lib/pillar/kinds.ts:367) adopting the same rule.
- 2026-11-17 by main-agent@ai-maestro-janitor: GitHub issue https://github.com/Emasoft/ai-maestro-janitor/issues/348 item 5 (LOCAL design back to the project slug folder) is scoped to this card; written now, handled later.

## Approval log

- 2026-10-23T16:12:04+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-23T18:03:50+0200 — column → blocked. waits on 78GMFJB4
- 2026-10-23T22:56:05+0200 — blocker 78GMFJB4 is complete (VERIFY-7, spec F20): trddgrep reads only the cwd realpath and has no input carrying the launch path. Two questions now belong to this card: (a) which input step 2 adds so trddgrep finds a slug-folder corpus, and (b) whether trddgrep run from a linked worktree finds the gitignored in-tree .claude/local/design at all (not measured). Still blocked, now on its NPT KQULEGL2 (does Claude Code cleanup touch <slug>/design/).
- 2026-10-23T22:58:21+0200 — question (b), the linked-worktree case, moved to TRDD-Q6UOJR8G (review of ca17df81); the ORDER rule is now decided under G26, not left to the owner (review of 03ef8b7a).
- 2026-10-23T22:59:31+0200 — qualifies the line above (review of 4cebe04b): G26 covers the ORDER rule only if golden G24/G15 do not reach LOCAL design placement; otherwise it is the owner's call.
- 2026-10-23T23:53:42+0200 — Q6UOJR8G measured (spec F21): trddgrep never finds LOCAL design by itself, only via --design-dir; F20's earlier clause that it finds LOCAL from cwd was wrong and is corrected.
- 2026-10-24T00:09:15+0200 — column → backburner by main-agent@ai-maestro-janitor. blocker KQULEGL2 complete (spec F22)
- 2026-10-24T00:10:28+0200 — KQULEGL2 complete (spec F22, Claude Code 2.1.309). Obligations for the migration: keep at least one file in each <slug>/design/ (an empty one can be rmdir-ed), and never name a design subfolder subagents, workflows, remote-agents, tool-results or mcp-tasks (they are swept like session data). F22 holds for 2.1.309 only, so step 3 adds a guard (the leftover-dir detector or a test) that alarms if a <slug>/design/ disappears (review of 6d6c1798).
