---
trdd-id: 39HTVD3N
title: trddgrep why omits intermediate blocked cards and double-lists blockers
column: blocked
status: tasked
created: 2026-10-07T04:32:25+0200
updated: 2026-10-07T05:15:38+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T04:32:25+0200
blocked-by: [ai-maestro#176]
pre-block-column: backburner
blocker-probe: gh issue view 176 --repo Emasoft/ai-maestro --json state
blocker-holds-if: match:OPEN
blocker-probe-canary: match:state
---

# trddgrep why omits intermediate blocked cards and double-lists blockers

## Symptom
`trddgrep why <id>` omits every intermediate blocked card from the blocker tree. The card own row is never printed, only its `blocked by` header, so its blockers appear attached to the previous sibling. When a card names the same blocker in both `npt:` and `blocked-by:`, each blocker is printed twice. Exit code is 0 and stderr is empty in every case.

## Reproducer (five cards in a scratch design/tasks folder, built with fastedit create, not in the repo)
- A: column todo
- R: column todo
- B: column blocked, blocked-by [R]
- Q: column blocked, blocked-by [B]
- P: column blocked, npt [A, B], blocked-by [A, B]
Run `trddgrep --design-dir <scratch>/design why Q` and `why P`.
- Expected for Q: Q, then B (blocked) as its own row, then ROOT R under B. Actual: Q, a `blocked by` header, a second `blocked by` header, ROOT R. B is not printed.
- Expected for P: A (ROOT) once, B once with R under it. Actual: ROOT A, a `blocked by` header with ROOT R under it, then the same three lines again. Two defects: B row missing (its subtree attaches to A), and A and B each printed twice because both npt and blocked-by name them.
- A card whose blocker file does not exist drops that blocker silently; documented in the code as intended (dangling refs are a lint finding), not a defect, mentioned only.
Real corpus: `trddgrep why JSQSJ3PZ` (npt and blocked-by both [JY0OBQZ4, G9Z8PXCM, HL3WBA2Q, IT5GEZDZ]) never prints IT5GEZDZ (blocked by NGLPQ7SW), so NGLPQ7SW looks like it blocks HL3WBA2Q; `trddgrep why IT5GEZDZ` alone is correct.

## Suspected location (PROVEN by reading the code, per the investigation)
scripts/trddgrep.mjs in the ai-maestro checkout, function `printChain` (lines 596-617): for a card with open blockers it prints only the `blocked by` header (line 615) and recurses; the card own row is printed only in the no-open-blockers branch (line 610). Duplicates: `blockerRefs` at line 411 concatenates `npt` and `blocked-by` without dedupe. Observed on ai-maestro package version 0.29.0, commit 9cf34aaf1 (2026-10-06); trddgrep has no --version flag.

Filed as Emasoft/ai-maestro issue 176 on 2026-10-07; the fix belongs in that repo; this card closes when a trddgrep release prints the intermediate card.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-07
2026-10-07: blocked on the external issue Emasoft/ai-maestro#176. NEXT ACTION: re-run the reproducer on each new trddgrep release.
2026-10-07: the probe canary is the bare word state because a quoted JSON form made this card unparseable by the board tool; note for the upstream issue.

## Approval log

- 2026-10-07T04:32:25+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-07T04:32:35+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on Emasoft/ai-maestro issue 176, the fix belongs in that repo
