---
trdd-id: 8UD3Q7K5
title: Memory scheduler should cheap-pre-check that a STRUCTURAL merge pair exists before emitting the consolidate marker — kill the ~226k no-op agent spawns
column: dev
created: 2026-06-25T21:38:45+0200
updated: 2026-06-25T21:38:45+0200
current-owner: ai-maestro-janitor
assignee: null
priority: 3
severity: MEDIUM
effort: S
labels: [memory, scheduler, wikimem, efficiency, perf, unattended-budget, consolidate]
task-type: bugfix
parent-trdd: null
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit]
runtime-targets: [macos, linux]
impacts: []
external-refs: ["github.com/Emasoft/ai-maestro-janitor/issues/64"]
---

# TRDD-8UD3Q7K5 — scheduler-side cheap STRUCTURAL precheck for consolidate to eliminate the no-op merge-agent spawns

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-06-25

### Current state
- **ROOT CAUSE confirmed by reading the source** (file:line below). The
  `[janitor-memory-consolidate]` marker is emitted on cadence alone; the
  per-chore content precheck (`memory_content_precheck.content_has_work`)
  returns `True` UNCONDITIONALLY for `consolidate`, so a corpus of
  categorically-unmergeable pages re-spawns a ~226k-token opus agent that can
  only re-abstain, every consolidate cadence (~2.5×/day).
- **FIX DESIGN settled**: add a cheap, zero-LLM `consolidate_has_work(root)`
  to `scripts/lib/memory_content_precheck.py` that returns True iff ≥2 candidate
  pages share the same `(tier, type)` with `tier ∈ memory_edit_verify._MERGEABLE_TIERS`
  (= `{"aspect","component"}`) — the EXACT necessary condition of `is_legal_merge`.
  Wire it into `content_has_work` exactly where SPLIT's `split_has_work` is wired.
  FAIL-OPEN; SUBJECT-sameness stays semantic/agent-discovered.
- **Tests + impl**: NOT YET DONE in this STATE block's first write. (Update on
  completion.)

### NEXT ACTION
1. Extend `memory_content_precheck.py` with `consolidate_has_work` + route
   `consolidate` through it inside `content_has_work`.
2. Add failing-first TDD tests in `tests/test_memory_content_precheck.py`
   (structural precheck) + `tests/test_memory_maintenance.py` (scheduler wiring:
   unmergeable corpus → no marker; mergeable corpus → marker).
3. `uv run pytest tests/test_memory_content_precheck.py tests/test_memory_maintenance.py -q` → all pass.
4. `uv run ruff check` + `uv run pyright` on the two changed files → clean.
5. Commit TRDD, then code+tests, citing issue #64. DO NOT push/publish.

### Load-bearing facts / gotchas
- `is_legal_merge(meta_a, meta_b)` (`scripts/lib/memory_edit_verify.py:~417`)
  refuses on THREE structural grounds: cross-tier, `tier ∉ {"aspect","component"}`
  (so a `hub` or a tier-less raw note is unmergeable), cross-type. The 4th refusal
  (distinct subject / a 3rd same-subject page) is SEMANTIC — only the agent can
  decide it. The cheap precheck therefore checks ONLY the structural necessary
  condition and stays FAIL-OPEN on subject sameness.
- `_MERGEABLE_TIERS = {"aspect", "component"}` and `parse_frontmatter(text)` both
  live in `memory_edit_verify.py` — IMPORT them (SSOT); do NOT re-define the tier
  set or re-implement frontmatter parsing in the precheck (a fork would drift the
  moment either moves; cf. TRDD-87935f21 "eliminate the duplicated source of
  truth").
- The candidate page set is `memory_scopes.iter_note_files(root)` — the SAME SSOT
  `split_has_work` uses (excludes `.maint-staging/`, `user-mem/`, generated/index
  basenames, `-proposed.md` detector reports). Do NOT re-scan with a raw `*.md`.
- Option A (no second cadence gate): a suppressed consolidate is simply not
  RETURNED by `_first_due_intervention`, so it is never picked → never
  `mark_ran`-stamped → stays due → re-checks (a cheap rglob + tiny frontmatter
  read, zero LLM, NO agent spawn) each fire → emits the instant a structural pair
  appears. This is the IDENTICAL stamp-semantics as 3XS3PDCF's split precheck and
  carries NO VJ8L465M-class double-gate (the scheduler stays the sole cadence
  authority; the agent still trusts the marker; no agent change).
- This is SCHEDULER-ONLY, additive, fail-soft (a heartbeat detector — never the
  exec path). Do NOT touch the agent skills.

### SUPERSEDED — do NOT carry forward
- (none yet)

### Durable artifacts to read before acting
- Issue #64 body (cached): `/tmp/issue64body.txt`.
- TRDD-3XS3PDCF (`design/tasks/TRDD-20260624_065323+0200-3XS3PDCF-…md`) — the
  split precheck this fix structurally mirrors; its STATE block §"FOLLOW-UPS"
  explicitly left CONSOLIDATE "semantic, agent-discovered". This TRDD REFINES
  that: the structural NECESSARY condition of a legal merge IS cheaply checkable,
  even though subject-sameness is not. So consolidate gets a *structural-only*
  precheck, not a full content gate.
- TRDD-VJ8L465M (`design/tasks/TRDD-20260624_023952+0200-VJ8L465M-…md`) — the
  double-gate fix; this fix MUST NOT reintroduce a second cadence gate.

## The problem (issue #64)

In one long session the heartbeat fired `[janitor-memory-consolidate]` twice
(~96 min apart). Each firing spawned `janitor-memory-subconscious-agent` in the
background, which re-evaluated the SAME LOCAL-scope candidates and abstained
identically — no transaction, no mutation (correct, safe) — at **~226k tokens
per run** for a guaranteed no-op. On any corpus that contains a cross-type
keyword-overlapping pair (common), this recurs indefinitely.

The two surfaced candidates can NEVER become legal merges without a content
change:
1. `feedback_*` + `reference_*` → a hard `is_legal_merge` refusal (cross-type).
2. A 9-note `cpv*` cluster → generic-keyword over-clustering; no genuine
   same-`(tier,type)` pair.

## Root cause (file:line evidence — read, not guessed)

- `scripts/detectors/memory-maintenance.py:235-240` — `_first_due_intervention`
  gates EVERY intervention (including `consolidate`) on
  `is_due(...) AND content_has_work(intervention, root, split_max_bytes=…)`.
- `scripts/lib/memory_content_precheck.py:78-84` — `content_has_work` handles
  ONLY `split` (the size gate); for `consolidate` (and every other chore without
  a cheap precheck) it `return True` unconditionally.
- ⇒ `consolidate` is emitted whenever cadence-due
  (`consolidation_per_day=2.5` → ~every 9.6h; `memory_settings.py:31`),
  regardless of whether ANY structurally-mergeable pair exists. The background
  agent then re-evaluates (~226k tokens) and abstains.

The split pass already has the cheap precheck (`split_has_work`, the size gate)
that prevents the analogous no-op. Consolidate's gate only checked "is it
cadence-due", not "could ≥2 pages actually merge". This TRDD adds the missing
structural "is there a mergeable cluster?" check, defined CHEAPLY without
spawning the agent.

## Fix design — `consolidate_has_work(root)` (cheap, zero-LLM, structural-only)

### What "no mergeable cluster" means CHEAPLY (the precise predicate)
`is_legal_merge` is the SSOT for merge legality. Its three STRUCTURAL refusal
grounds (cross-tier / tier ∉ `{aspect,component}` / cross-type) are computable
from each page's frontmatter ALONE — no body read, no LLM, no agent. A merge is
therefore structurally possible iff the corpus contains at least one PAIR of
candidate pages with the SAME `(tier, type)` where `tier ∈ _MERGEABLE_TIERS`.

`consolidate_has_work(root)`:
1. `pages = memory_scopes.iter_note_files(root)` (the shared candidate SSOT).
2. For each page, read its text, `parse_frontmatter(text)` (the
   `memory_edit_verify` SSOT), keep `(tier, type)` when `tier ∈ _MERGEABLE_TIERS`.
3. Count per `(tier, type)` key. Return True iff any key has count ≥ 2.
4. Unreadable page → skip (defence: an unreadable page is not provably part of a
   mergeable pair; if nothing else pairs, we correctly report no work).

### Why this is FAIL-OPEN and correct
- If a structural pair EXISTS, we dispatch (True) — the agent then applies the
  SEMANTIC gate (same subject? a 3rd same-subject page?) and may still abstain.
  We never suppress a *possibly-real* merge; the subject decision stays with the
  agent. (So candidate #2's `cpv*` cluster: IF ≥2 of those 9 pages share a
  `(tier,type)` we still dispatch and the agent abstains on subject — we only kill
  the case where NOT EVEN a structural pair exists, which is the issue's case #1
  and any all-distinct-`(tier,type)` corpus.)
- If NO structural pair exists, `is_legal_merge` would categorically refuse EVERY
  pair → the agent can ONLY abstain → suppress the dispatch. Provably idle.
- Cost: one rglob + a tiny leading-frontmatter parse per candidate page — the
  same order of cost as `split_has_work`'s `stat` loop, run at most once per
  heartbeat for an already-cadence-due consolidate (the `and` short-circuits).

### Wiring (exactly where SPLIT's is wired)
In `content_has_work`, add an `elif intervention == "consolidate": return
consolidate_has_work(root)` branch — alongside the existing `split` branch, ahead
of the fail-open `return True`. No scheduler change beyond what 3XS3PDCF already
built: `_first_due_intervention` already calls `content_has_work`, so consolidate
now gets its structural gate for free, with the Option-A stamp semantics intact.

### What stays unchanged (anti-regression)
- VJ8L465M: no second cadence gate (the precheck is an additional EMIT condition,
  not a cadence re-check; `mark_ran` stays the sole cadence authority).
- 3XS3PDCF: `split` behaviour and its fail-open contract are untouched; every
  un-prechecked chore (harvest/repair/atomize/conflict) still fails open.
- The agent skills are NOT touched (they still trust the marker).
- `conflict` stays agent-discovered: its due-ness is "are there CONTRADICTORY
  facts?", a genuinely semantic question with no cheap structural proxy. (Only
  consolidate has the `is_legal_merge` structural necessary-condition to exploit.)

## TDD test plan

### `tests/test_memory_content_precheck.py` (extend, same temp-dir style, no mocks)
- `consolidate_has_work` True when ≥2 pages share `(tier=component, type=project)`.
- `consolidate_has_work` True for a same-`(tier=aspect, type=reference)` pair.
- `consolidate_has_work` False on the issue's exact case: one `feedback`/aspect +
  one `reference`/aspect (cross-type) → no structural pair.
- `consolidate_has_work` False when every page has a DISTINCT `(tier,type)`.
- `consolidate_has_work` False when pages share a `type` but `tier=hub` (not in
  `_MERGEABLE_TIERS`) — hubs are not mergeable leaves.
- `consolidate_has_work` False when pages share a generic keyword but have no
  `tier` frontmatter (raw buffer notes) → unmergeable.
- `consolidate_has_work` False on empty / missing dir.
- `consolidate_has_work` ignores `.maint-staging/` + `user-mem/` (via the SSOT
  `iter_note_files`): a mergeable-looking pair placed ONLY in staging → False.
- `content_has_work("consolidate", …)` delegates to `consolidate_has_work`
  (True/False round-trip).
- Existing `test_content_has_work_unprechecked_chores_fail_open` MUST drop
  `consolidate` from its fail-open set (it now has a precheck) and keep
  harvest/repair/atomize.

### `tests/test_memory_maintenance.py` (extend — scheduler wiring)
- Unmergeable LOCAL corpus + consolidate cadence-due → `_first_due_intervention`
  does NOT return `consolidate` → `main()` emits NO `[janitor-memory-consolidate]`
  marker AND does not `mark_ran` consolidate (Option-A not-stamped invariant).
- Mergeable LOCAL corpus (≥2 same-`(tier,type)`) + consolidate cadence-due →
  `_first_due_intervention` returns `consolidate` → marker emitted (still
  dispatches; the agent decides subject).
- (Reuse the existing test harness that seeds scope dirs + stamps; mirror the
  split-fires tests added by 3XS3PDCF.)

## Derived tasks (DERIVED — consequences considered)
- **D1 — keep the `_MERGEABLE_TIERS`/`parse_frontmatter` import as the SSOT.**
  Importing from `memory_edit_verify` couples the precheck to it. That is the
  CORRECT coupling (single source for merge legality); the alternative (copying
  the tier set) is the divergence bug TRDD-87935f21 fixed. No new module needed.
- **D2 — `iter_note_files` recurses into `wiki/`.** The coexistence model
  (TRDD-ab232dbd) keeps curated pages (with `tier`) under `wiki/`; raw buffer
  notes (no `tier`) at the root. `iter_note_files` recurses both, and only
  curated pages carry a `tier`, so the structural pairing naturally considers
  exactly the mergeable (curated) pages. No special-casing required; verified by
  reading `iter_note_files` (rglob) + `is_curated_wiki_page` (tier ⇒ curated).
- **D3 — update the module docstring** of `memory_content_precheck.py` so its
  "today only SPLIT has a precheck … CONSOLIDATE/CONFLICT are genuinely SEMANTIC
  and stay agent-discovered" note reflects that CONSOLIDATE now has a
  STRUCTURAL-only precheck (subject-sameness still agent-discovered).
- **D4 — no doc/CLAUDE.md map churn**: the project-map fences auto-regenerate;
  `memory_content_precheck.py` gains one function, picked up on the next map pass.

## Why this is the right scope (two-perspective review)
- *Perfectionist*: could also pre-filter at the librarian (issue's fix #1 "do not
  surface a categorically-refused candidate") and/or add structural-abstain
  memoization (fix #2). Doing it at the SCHEDULER precheck layer is the minimal,
  highest-leverage fix that kills the ~226k spawn at the source for EVERY corpus,
  composes with the already-shipped 3XS3PDCF machinery, needs no librarian change,
  and needs no new persisted memo state. The librarian pre-filter is a valid
  separate refinement (it would also clean the surfaced-candidate report), but it
  is NOT required to stop the token waste and is out of scope here.
- *Pragmatist*: one small pure function + one `elif` + tests. Fail-open, no agent
  change, no double-gate, no new state. Ship it.
