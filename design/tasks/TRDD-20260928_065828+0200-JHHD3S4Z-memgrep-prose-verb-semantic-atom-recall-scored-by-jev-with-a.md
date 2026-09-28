---
trdd-id: JHHD3S4Z
title: memgrep prose verb — semantic atom recall scored by Jev with a persistent query-atom score cache
column: todo
status: tasked
created: 2026-09-28T06:58:28+0200
updated: 2026-09-28T13:42:36+0200
current-owner: user
created-by: user
task-type: feature
min-approval-requirement: none
assignee: user
mandate: true
mandated-by: none
approved: true
approval-judge: user
approval-datetime: 2026-09-28T06:58:28+0200
---

# memgrep prose verb — semantic atom recall scored by Jev with a persistent query-atom score cache

# memgrep prose — semantic atom recall via Jev

Owner directive 2026-09-28: add a memgrep verb that searches atoms by natural-language PROSE instead of key-phrase/metadata matching. Every atom in the wikimem is scored by Jev (jgrep's decision model: TypeSafe native / OpenRouter / gateway, key from env) with one yes/no question per atom; the verb prints ALL atoms above a 0.9 default threshold (-t overridable), keeping the existing grep conveniences: date filters, sorting, view modes (description / body / full atom incl. notes, superseded versions, lessons, references), scope selection (user/project/local), page/topic restriction.

## Owner decisions (verbatim intent)

- NO prefilter cap: "there should be no cap, i need jev to score all atoms in the wikimem. otherwise some memories could be missed. to reduce some jev work, implement a cache for all the pairs query-atom, adding a cache of type: (query,atom) -> score. so that if the same query is executed multiple times, jev will only need to score it once." The (query,atom) cache is the cost lever, never a relevance cap. Only caller-chosen filters (scope/page/date) shrink the set.
- View modes must include "all notes, superseded versions and lessons learned, and references". Superseded atoms are SCORED by default (status is not a relevance gate; the threshold is).
- Scored text per atom: body + resolved [^N] lessons (owner AskUserQuestion choice), plus desc+keywords in the chunk.
- Privacy: bodies leave the machine — --help warning + stderr notice; gateway mode for in-infrastructure.

## Approved plan

The full reviewed plan (4 reviewed commits) is at .claude/plans/dreamy-rolling-walrus.md — its content is the implementation contract. Key anchors: ProseScorer trait seam; ureq 2.x + serde; batching 16x16; cache key = (provider, model, sha256(normalized query + sha256(full chunk text))); gather reuses recall's index+walk path with superseded-exclusion overridden off; output reuses finalize_recall verbatim (score = p*1000; --json carries raw float p); exit 0/1/2 crate convention; partial-failure isolation (hits still print, exit 2, typed breakdown on stderr).

Review chain: the plan went through two adversarial review rounds; CUREs applied: superseded inclusion default-on + cache key hashes the exact chunk payload + query normalization defined (trim/collapse/case-fold) + json raw float + sort default score-desc + partial-failure semantics + exit codes.

## Implementation

PENDING — dispatch per plan sequencing (A2 step-1 worker owns memory.rs first; prose commits follow).
2026-09-28 commit 3 landed (b803ad99) via lean-worker, main-verified: cargo check clean, 306+159 tests green (2 new offline prose_tests), live smoke via fake Jev gateway (cache-hit-against-dead-server, no-cap default, threshold/sort/--top/json). Commit 3b (88dfc7eb): jev.rs parse_answer now accepts the OpenRouter type-keyed probability shape ({"noul":0.06,"type":"noul"}) — every real OpenRouter response previously parsed as Malformed; found by the worker's live smoke; +1 test. Remaining: commit 4 (polish — --help privacy warning, live e2e #[ignore] test, README/rule touch-up).

## Approval log

- 2026-09-28T06:58:28+0200 — MANDATE issued by user (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-28T06:58:35+0200 — column → todo by user.
