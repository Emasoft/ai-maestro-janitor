---
trdd-id: JHHD3S4Z
title: memgrep prose verb — semantic atom recall scored by Jev with a persistent query-atom score cache
column: testing
status: tasked
created: 2026-09-28T06:58:28+0200
updated: 2026-09-28T15:38:04+0200
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
2026-09-28 commit 4 landed (5387c527) via lean-worker, main-verified (307+159 tests green, cargo check clean): --help privacy warning (scored text is SENT to the backend; gateway option), no_superseded_flag_removes_superseded_atoms_from_candidates (review NOTE-4 follow-up), prose_live_backend_scores_real_query_without_error #[ignore]-gated live harness (worker ran it by hand against the real backend, pass), prose documented in SKILL.md (the crate has no README; worker verified none ever existed) with the privacy warning. SEQUENCE COMPLETE: commits 1-4 landed, review chains closed. Card ready for testing.
2026-09-28 review of commit 4 — CURE recorded, two residuals are NAMED OPEN ITEMS for the testing column: (a) the shipped rule markdown-memory-recall.md does not yet mention the prose verb (the plan's 'rule touch-up' leg landed on SKILL.md instead, since scripts/memgrep has no README; one sentence owed on next touch of that rule); (b) the live e2e has run only in the worker's environment (hand-run, honestly attributed) — testing-column exit needs a main-agent replay (TYPESAFE_API_KEY=... cargo test -- --ignored prose_live) or an owner waiver. Follow-up note: the toggle test pins the filter semantics, not the flag-to-struct wiring — cheap extension on next verb touch. Commit-type nit: 5387c527 is 'docs(memgrep)' but ships two tests (harmless mislabel).
2026-09-28 box (b) TICKED — live e2e replayed by the main agent, provider substituted with disclosure. Machine fact: TYPESAFE_API_KEY does not exist here (only OPENROUTER_API_KEY in .zprofile), and the #[ignore] test's gate (memory.rs:14175) early-returns without a key — so the box's literal command trivially passes with zero network (confirmed: two cargo runs finished in 0.00s). Honest replay instead: CLI prose -t 0 --output medium 'which memory covers the review fork spawn rule?' /tmp/prose-e2e-fix/mem (query is the FIRST positional — earlier invocations with path-first were rejected as 'no atoms'), hand-built 1-atom fixture, fresh EMPTY XDG_CACHE_HOME, OpenRouter default resolution. Evidence of a real round-trip: stderr '[prose] sending 1 atoms to openrouter', exit 0, atom printed at p=0.87, cache entry written 15:36:07 (run 15:36:04) into the empty dir — impossible from cache or early-return.

## Approval log

- 2026-09-28T06:58:28+0200 — MANDATE issued by user (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-28T06:58:35+0200 — column → todo by user.
- 2026-09-28T14:04:41+0200 — column → testing by user.

## Acceptance

- [ ] the shipped rule markdown-memory-recall.md mentions the prose verb (one sentence, on next touch of that rule) — commit-4 review residual (a)
- [x] live e2e replayed by the main agent (TYPESAFE_API_KEY=... cargo test -- --ignored prose_live) or owner waiver recorded — commit-4 review residual (b)
