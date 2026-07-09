---
trdd-id: 3XS3PDCF
title: Memory scheduler should cheap-pre-check content-due-ness before emitting filesystem-checkable chore markers — kill the ~240k no-op agent spawns
column: dev
created: 2026-06-24T06:53:23+0200
updated: 2026-07-09T15:33:52+0200
current-owner: ai-maestro-janitor
assignee: null
priority: 3
severity: MEDIUM
effort: M
labels: [memory, scheduler, wikimem, efficiency, perf, unattended-budget]
task-type: refactor
parent-trdd: null
relevant-rules: []
release-via: publish
test-requirements: [unit]
runtime-targets: [macos, linux]
impacts: []
external-refs: []
---

# TRDD-3XS3PDCF — scheduler-side cheap content-precheck to eliminate no-op memory-agent spawns

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-24

**2026-07-04 board-reconciliation (TRDD-GB3Z9U9J) — PARTIALLY SHIPPED, stays dev:** the split-MVP is PUBLISHED (441d467, in v0.18.1 — the "committed locally, NOT yet published" note below is SUPERSEDED); consolidate gained its own structural precheck via TRDD-8UD3Q7K5/issue #64 (636e7df, v0.24.15). Remaining in-scope follow-ups: harvest precheck (UNBLOCKED 2026-07-08 — see the entry below), split refinement (memory_content_precheck.py:142 documents them as follow-ups).

**2026-07-08 22:50 — HARVEST PRECHECK UNBLOCKED (the last missing gate).** The blocker
(TRDD-ab232dbd's model-in-flux) is RESOLVED: the coexistence-mirror harvest shipped in
v0.33.0 (mirror raw buffer notes into `wikimem/`, never touch the buffer) and ran LIVE
tonight. Live evidence of the remaining drain: the 22:45 heartbeat-dispatched harvest on
LOCAL abstained "nothing due — all 38 notes curated, 0 raw to mirror" at a cost of
**257,826 tokens** (report `reports/memory-subconscious-agent/20260708_224524+0200-harvest-local-nothing-due.md`);
at `harvest_per_day=1` × 3 scopes ≈ 750k/day of avoidable no-op. The now-stable predicate
for `harvest_has_work(root)`: any top-level note that is NOT a curated wikimem page
(`is_curated_wiki_page` False) AND not yet watermarked mirrored
(`memory_settings.harvest_note_is_mirrored` False) — both already-shipped helpers; pure
filesystem read, same fail-open discipline as the split gate. **IMPLEMENTED same
night (commit 10f899b, 23:0x):** `harvest_has_work(scope, root)` mirrors the skill's
step-1 scan exactly (top-level glob only — skill parity documented, a nested note never
claims work the skill won't do); `content_has_work` gained a keyword-only `scope`
(fail-open when absent — the watermark ledger is scope-keyed); scheduler passes
`scope=scope`. 9 predicate tests + 2 gating tests + the due-emits-marker[harvest] seed
fix — 80/80 green, ruff clean.

**2026-07-09 — CONFLICT PRECHECK TOO (commit f2056ca): ALL SIX CHORES NOW GATED.** A
live conflict pass (2026-07-08 23:01) abstained on an empty `### Conflict candidates`
section at 260,931 tokens — and the pass is NOT self-discovering: the skill's own
precondition reads the librarian's `memory-reorg-proposed.md` and mandates
"Empty/absent → stop", so due-ness is mechanically checkable (discovery stays the
librarian's semantic job). `conflict_has_work` pins writer/reader parity to the
librarian's literal heading + `- (none)` sentinel; absent file = the skill's own idle
case; unreadable = fail-open. 7 unit + 2 gating tests; the two
"unconditional fail-open" collateral tests updated; 88/88 green, ruff clean.
**SUPERSEDED — "Banked locally; rides the next publish" is stale:** `f2056ca` (conflict)
and `10f899b` (harvest) both shipped in **v0.34.0**, and are ancestors of v0.35.3.

**2026-07-09 — CONSOLIDATE STILL DRAINS: its structural gate is NECESSARY but far from
SUFFICIENT** (evidence below; decisions carried here because the cited reports are
gitignored/ephemeral). Two live consolidate passes dispatched on 2026-07-08 both
**ABSTAINED** after a full agent spawn:

- USER scope, 21:15 — `reports/memory-subconscious-agent/20260708_211500+0200-consolidate-user-scope.md`
- LOCAL scope, 23:05 — `reports/memory-subconscious-agent/20260708_230514+0200-consolidate-local-abstain.md`

`consolidate_has_work` (TRDD-8UD3Q7K5 / issue #64) asks only the STRUCTURAL necessary
condition of `is_legal_merge`: *does any page pair share the same `tier` (∈ aspect,
component) and the same `type`?* Both scopes hold many `tier: component, type: reference`
pages, so the gate passes, the marker fires, the agent spawns — and then abstains on
**subject**, which the gate never examined. Both reports independently confirm zero
same-subject pairs (the many `oauth-rotator-*` pages are distinct facets; the
`wikimem-atom-block-properties*` and `ai-maestro-fleet-hub*` families are correct
post-SPLIT shapes that `is_legal_merge` would itself refuse to re-fragment).

**Do NOT graft the conflict-style librarian sentinel onto consolidate.** It looks like a
drop-in (`conflict_has_work` reads the librarian's `### Conflict candidates` + `- (none)`
sentinel) but it would silently change semantics. The CONFLICT skill's own precondition
mandates *"Empty/absent → stop"*, which is what makes reader/writer parity safe there. The
CONSOLIDATE skill does **its own discovery beyond the librarian's list** — see the LOCAL
report's step 2, where it read `### Aggregation candidates: (none)` and *then* independently
narrowed by recency + title similarity. Gating on `(none)` would suppress discovery the
skill is contractually still performing. Two honest options, both design changes:
(a) tighten the structural predicate with a cheap subject-overlap signal on top of
tier+type, or (b) make the CONSOLIDATE skill's discovery contract librarian-authoritative
(adopting the "Empty/absent → stop" precondition), and only then gate on the sentinel.

**The drain is a SCHEDULER problem, not an editor-correctness problem.** A scratch
end-to-end merge test the same evening
(`reports/memory-subconscious-agent/20260708_201642+0200-scratch-consolidate-test.md`)
drove `begin → stage → commit` on an isolated scope root (`JANITOR_GLOBAL_STATE_DIR`
pointed at a scratch dir so the real, intentionally-SET kill-switch was never touched) and
proved the transaction core correct: both sources' facts merged verbatim, `ocd` kept at the
older of the two, `lmd` bumped, the retired page deleted, staging cleaned on success.

Ancillary, worth keeping: in that session the native `Write`/`Edit` tools refused every
staged-file write with *"File has not been read yet"* — reproduced on a brand-new probe file
immediately after Reading it, so it was environmental, not path-specific. Worked around by
writing staged bytes via `uv run <script>.py`. That stays inside the skill's constraint
("edit only inside staging"); the transaction core's hash/verify gate — not the identity of
the writing tool — is what actually proves no live-page corruption.

**Both abstains, and the 2026-07-09 heartbeat's librarian line (`0 aggregation + 0 conflict
+ 17 page-shape + 95 link/sync across 3 scopes`), agree the real backlog is REPAIR-pass
work** (dangling footnote defs, `[[links]]` to missing targets, orphan pages, ~19 one-sided
links needing reciprocals) — not consolidation. Remaining in this TRDD: the split "over-cap
AND splittable" refinement, plus the consolidate sufficiency question above.

### ✅ SPLIT-MVP IMPLEMENTED + TESTED (2026-06-24 ~08:42, committed locally, NOT yet published)
The highest-value slice — the **SPLIT** content-precheck — is done, TDD'd, ruff-clean,
and committed locally (deferred publish: deep-night, no OAuth rotation alternate; ships
on the next `publish.py` release). Split is the single biggest no-op drain: `split_per_day=4.5`
with a corpus where NO page is over the 36000-byte cap (largest ~12 KB) = ~4.5 × 235k ≈
**~1M tokens/day of pure no-op spawns**, now eliminated.

What landed:
- **`scripts/lib/memory_content_precheck.py`** (NEW) — `content_has_work(intervention, root,
  *, split_max_bytes)` + `split_has_work(root, *, max_bytes)`. FAIL-OPEN: only a chore whose
  idleness is cheaply PROVEN (today: split's size gate, excluding `.maint-staging/`) is
  suppressed; every other chore returns True (unchanged cadence-only). A non-positive cap →
  fail-open (never suppress on a config glitch). This is the SSOT for the size gate, sharing
  the cap (`memory_settings split_max_bytes`) + the staging-exclusion with the split skill.
- **`scripts/detectors/memory-maintenance.py`** — `_first_due_intervention` now gates on
  `is_due AND content_has_work` (+ `_split_max_bytes()` fail-open cap reader). Option A falls
  out for free: a suppressed split is never *picked* → never `mark_ran`-stamped → stays due →
  re-checks each fire (a cheap rglob, zero LLM, NO agent spawn) → emits the instant a page goes
  over cap. NO VJ8L465M double-gate (scheduler stays the sole cadence authority; agent still
  trusts the marker; no agent change).
- **Tests**: `tests/test_memory_content_precheck.py` (10 pure unit tests) +
  `tests/test_memory_maintenance.py` (4 NEW precheck tests incl. the Option-A
  not-stamped-then-fires invariant + the `.maint-staging` exclusion; 3 existing split-fires
  tests seeded an over-cap page). **29/29 pass, ruff clean.**

### ✅ REPAIR + ATOMIZE PRECHECKS IMPLEMENTED (2026-07-08, this session)
The two remaining unblocked follow-ups landed, TDD'd (65/65 green across
test_memory_content_precheck.py + test_memory_maintenance.py, ruff clean):
- **`repair_has_work`** — STRUCTURAL page-shape gate mirroring `verify_repair`'s own
  bars via the SSOT constants (`_REQUIRED_FM_KEYS`, `_VALID_TIERS`,
  `_LESSONS_HEADING`): missing/partial frontmatter (incl. RAW buffer notes — the
  skill explicitly upgrades them), invalid tier, NESTED ocd/lmd placement (issue
  #56 — raw-line check, since parse_frontmatter flattens), missing Notes section,
  inverted tier shape. DOCUMENTED RESIDUAL: the two SEMANTIC-only defects
  (answer-shaped description, own one-sided link) are not cheaply detectable — a
  corpus whose ONLY defects are semantic stays suppressed until the librarian
  surfaces them or a structural defect appears (same documented-approximation trade
  as split's size-only gate).
- **`atomize_has_work`** — free-prose gate mirroring the skill's exact candidate
  scan: CURATED pages only (`is_curated_wiki_page` — raw buffer notes never
  candidates), zero `_ATOM_MARKER_RE` markers, ≥1 substantive body line (else the
  skill's "free-prose-leaf" abstain case).
- **L-11 (libs audit) fixed in passing**: every precheck's unreadable-page path now
  FAILS OPEN (`return True`) instead of skip-and-continue — an unreadable page is
  not provably idle.
- Scheduler unchanged except docstring (the generic `content_has_work` dispatch just
  gained the two branches); Option-A never-stamped-when-suppressed invariant covered
  by new gating tests for both chores.
- HARVEST precheck stays BLOCKED (below) on TRDD-ab232dbd #231/#232.

### 🔻 FOLLOW-UPS (deliberately NOT in this MVP — the dispatch is built to extend)
- **HARVEST precheck — BLOCKED (not merely deferred): the harvest WORK-predicate is in
  active flux.** Verified 2026-06-24 by reading the actual sources: the harvest `SKILL.md`
  still describes the OLD stub-reduction behavior (verify → reduce `MEMORY.md` to the stub),
  but `memory_scopes.py` already carries the NEW coexistence model (TRDD-ab232dbd, "USER
  decision 2026-06-23"): `WIKI_SUBDIR` + `is_curated_wiki_page` — raw buffer at the scope
  root, curated pages in `wiki/`, harvest MIRRORS raw→wiki and NEVER touches the buffer. And
  the coexistence-harvest itself (TRDD-ab232dbd, #231) is PENDING while atom-indexing
  harvest/migration (TRDD-3b9b2040, #232) is IN-PROGRESS. A precheck written against EITHER
  model would wrong-suppress against the other or go stale the moment #231/#232 land — the
  exact wrong-suppress hazard fail-open exists to avoid. So this stays BLOCKED until harvest
  behavior stabilizes (after #231/#232); meanwhile `content_has_work`'s fail-open default
  keeps harvest at zero-regression cadence-only. (Split was safe to ship precisely because
  its predicate — size > cap — is STABLE; harvest's is not, yet.)
- **REPAIR / ATOMIZE prechecks** — per-page shape scans (malformed frontmatter / un-atomized
  body). Cheap-ish but need each skill's predicate read; repair is a LOWER-value target (it
  often has genuine work, unlike split). Also fail-open today.
- **SPLIT refinement** — the size gate is the COMMON-case fix; refine to "over-cap AND
  splittable (not tier:component, ≥2 sections)" to also suppress the rare over-cap-but-
  unsplittable no-op.
- **PUBLISH** — ship the whole thing via `publish.py` when the USER is present (or returns).
  CORRECTED WHY (2026-06-24, supersedes the earlier "budget" reason): the test-suite + CPV
  cycle is LOCAL compute (pytest + `validate_plugin.py`), so it costs almost no OAuth budget —
  only the handful of orchestration turns. The real reason to keep the fix banked is that
  `publish.py` performs an OUTWARD-FACING, hard-to-reverse GitHub release + marketplace
  publish; running that UNATTENDED at deep-night with the USER away is the wrong solo risk —
  a mid-way failure leaves a partial release whose cleanup (revert version, delete tag, delete
  GH release) is destructive and user-visible. That is a "confirm-first" action INDEPENDENT of
  budget, so it waits for the USER's PRESENCE, not merely for a rotation alternate. The
  split-MVP is done + tested (29/29) and ready to ship the moment the USER is back.

### The finding (observed live, autonomous overnight session 2026-06-24)
Two background `janitor-memory-subconscious-agent` opus passes spawned by heartbeat
markers BOTH no-op'd at ~240k tokens each:
- `[janitor-memory-harvest]` → "NOTHING DUE" (LOCAL+USER MEMORY.md stubbed, zero stray pages). 245k tokens.
- `[janitor-memory-split]` → "NOTHING DUE" (no page over the 36000-byte cap; LOCAL largest 12328 B, USER 11869 B). 235k tokens.

~480k tokens spent to discover "nothing to do." On an UNATTENDED overnight janitor
(the immortality use-case) with several such markers/day, this is a large, recurring
budget drain — and it directly worsened tonight's near-freeze.

### Why VJ8L465M did NOT cover this (and where its conclusion is too broad)
TRDD-VJ8L465M (complete) fixed the CADENCE-abstain no-ops: atomize/conflict/repair
re-checked `is_due` agent-side after the scheduler already stamped at emit (a double
gate), so they abstained on cadence. Fixed by removing the agent-side re-check — the
scheduler `memory-maintenance.py` is the sole cadence authority, is_due-checks + stamps
at emit (~line 278). VJ8L465M dismissed the RESIDUAL CONTENT-abstain no-op as
"inherent — the scheduler can't know content-due-ness cheaply."

That conclusion is TOO BROAD. For the FILESYSTEM/STRUCTURE-checkable chores, the agent's
own content check IS a cheap, zero-LLM filesystem op the scheduler could run BEFORE
emitting the marker:
- SPLIT: `any page > split_max_bytes` (the agent did `find -size +<cap>c`).
- HARVEST: `MEMORY.md not yet stubbed OR any stray non-stub .md` (cheap read + count).
- ATOMIZE / REPAIR (likely): page-shape checks (multiple facts in one page / missing
  frontmatter) — cheap-ish structural scans; CONFIRM cheapness during implementation.
Only the SEMANTIC chores genuinely need the agent to discover due-ness:
- CONFLICT (are there contradictory facts?) and CONSOLIDATE (duplicate same-subject
  pages?) require reading + reasoning over content → leave as agent-discovered.

### The change
Add a per-chore CHEAP content-precheck to the scheduler's emit gate
(`memory-maintenance.py`): for the filesystem-checkable chores, emit the marker (and
stamp) ONLY when the cheap check finds actual work. Reuse the EXACT predicate the
corresponding agent skill uses — single source of truth; do NOT fork the cap/stray
logic. Lift it into `memory_settings` (or a shared helper) that both the scheduler and
the skill call.

### THE SUBTLE BIT (resolve at design time — the only real risk)
Cadence-stamp semantics when cadence-due but NO content:
- Option A (re-check each heartbeat, no stamp): cadence-due + no-content → run the cheap
  check every heartbeat, emit nothing, do NOT stamp. The instant content appears it
  emits. Most responsive; the cheap check runs ~every 5 min (fine — a filesystem find,
  zero LLM).
- Option B (stamp-and-skip): cadence-due + no-content → `mark_ran` and skip until next
  cadence. Cheaper (no per-heartbeat find) but LESS responsive (a page that goes
  over-cap right after a skip waits a full cadence interval).
RECOMMEND Option A. VERIFY it does NOT reintroduce a VJ8L465M-class double-gate: the
scheduler stays the sole cadence authority; the content-precheck is an ADDITIONAL emit
condition, not a second cadence gate. Agents keep TRUSTING the marker (no agent change).

### NEXT ACTION (when budget is clean + ideally a rotation alternate exists)
1. Read `scripts/detectors/memory-maintenance.py` emit logic (~line 278) + the
   split/harvest SKILL.md content predicates + `memory_settings.is_due`/`mark_ran`.
2. Extract each filesystem-checkable chore's content predicate into a shared,
   unit-testable helper (single source of truth with the agent skill).
3. Gate the scheduler's emit on `is_due AND content_exists` for those chores; keep
   conflict/consolidate cadence-only (agent-discovered).
4. Resolve the stamp semantics (Option A recommended) with tests proving: (a) no marker
   when cadence-due but no content, (b) marker the moment content appears, (c) no
   VJ8L465M-class double-gate (agent still trusts the marker).
5. TDD in `tests/test_memory_maintenance.py`. Ship via publish.py.

### Load-bearing facts
- Evidence (gitignored/ephemeral — cited, not relied on):
  `reports/memory-subconscious-agent/20260624_060415+0200-harvest-nothing-due.md`,
  `…/20260624_064046+0200-split-nothing-due.md`.
- The cap is `split_max_bytes` (36000 B observed) via `memory_settings`.
- Do NOT touch the agent skills (VJ8L465M already aligned them to trust-the-marker);
  this change is SCHEDULER-ONLY, additive, fail-soft (a detector).
- Non-bricking: `memory-maintenance.py` is a heartbeat detector, not the exec path.

## Why this is deferred (not done at discovery time)
Authored during the deep-night autonomous session with NO OAuth rotation alternate
(fmuaddib dead) and a glitchy usage API. A subtle cadence-stamp change to the very
scheduler VJ8L465M just fixed is exactly the work to do with a clean budget + a rotation
safety net, not rushed unattended. Per /go-on-yourself: TRDD the change, implement when
conditions allow.
