---
trdd-id: GB3Z9U9J
title: Board reconciliation sweep — close shipped-but-open TRDDs, merge duplicates, triage stale issues
column: dev
created: 2026-07-04T04:46:15+0200
updated: 2026-07-07T14:46:35+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 2
severity: MEDIUM
effort: M
task-type: audit
parent-trdd: null
relevant-rules: []
release-via: none
labels: [board-hygiene, trdd]
external-refs: ["https://github.com/Emasoft/ai-maestro-janitor/issues/67", "https://github.com/Emasoft/ai-maestro-janitor/issues/70"]
---

# TRDD-GB3Z9U9J — Board reconciliation sweep

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-07

- **Steps 1+2 DONE** (executed 2026-07-04, committed 2026-07-07): 17 TRDDs reconciled —
  11 closed (`published`/`complete`: 87935f21, 3f7b6807, aebedbff, fe45babc, T198DT1W,
  7DVNHLOP, DKEYCHN7, DGROUPAB, F3AUDLOG, KEEPQRTN, AKH7JRAA), 1 superseded (3ab0397e →
  superseded-by 6f226399), 5+ annotated "PARTIALLY SHIPPED, stays dev/dispatch" (32acd15f,
  dfc0959a, 47df698b, 56d24c02, 3XS3PDCF, YRPUSIFY). Evidence SHAs spot-verified
  (d14510a/aa4c593/10ee8d1/441d467/5687848 all exist and match their TRDDs).
- **NEXT ACTION — step 3:** triage GitHub issues #67 (weekly audit drift) and #70
  ([janitor-reload] marker UX) against current code; close with evidence or spawn a TRDD.
- **Then step 4:** investigate why the reconciliation detector (TRDD-15ECPBSA) never
  flagged the drift; fix + regression-test, or record why out-of-scope.

## The task

The 2026-07-04 plugin-state evaluation found the TRDD board materially out of sync with
the shipped code: 17 TRDDs sit in `dev`, but at least two describe features that are LIVE
(TRDD-7DVNHLOP — the PreCompact handoff hook fires on every compaction; TRDD-AKH7JRAA —
ci-status is in the CLAUDE.md live detector roster). A duplicate pair covers the same
heartbeat durable-downgrade problem (TRDD-6f226399 in `backburner` vs TRDD-3ab0397e in
`todo`). Issue #67 (weekly audit drift) and #70 ([janitor-reload] marker UX — likely stale
now that the janitor-reload-plugins skill injects the command itself) are unresolved. A
wrong board makes every future evaluation start from false premises.

## Plan

1. For each `dev`/`todo`/`dispatch` TRDD, verify against the code (grep the feature's
   entry points + tests) whether it is shipped, partially shipped, or untouched; move
   shipped ones to `complete`/`published` with `implementation-commits:` backfilled from
   `git log -S`.
2. Merge the duplicate heartbeat-survival pair: keep the more complete one, mark the other
   `superseded` with `superseded-by:` (N→1 group semantics).
3. Triage issues #67 and #70 against current code; close with evidence or convert the
   residual gap into a TRDD.
4. Investigate WHY the published reconciliation detector (TRDD-15ECPBSA) did not flag
   these — fix its gap or its cadence if broken, else record why they were out of scope.

## Derived tasks

- If step 4 finds a detector bug → fix + regression test in the same change.
- Any TRDD found half-shipped → update its STATE block so the next resume is truthful.

## Verification

- `grep -c "^column: dev" design/tasks/*.md` drops to only genuinely in-progress work.
- No two open TRDDs cover the same subject; every closed issue has an evidence comment.
