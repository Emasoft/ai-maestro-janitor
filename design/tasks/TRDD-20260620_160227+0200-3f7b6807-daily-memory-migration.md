---
trdd-id: 3f7b6807-c2be-4726-a098-4bcfee13d5d5
title: Daily memory-system migration — staggered harvest + PROJECT gitignore-exception enforcer
column: dev
created: 2026-06-20T16:02:27+0200
updated: 2026-06-20T16:27:00+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 1
severity: MEDIUM
effort: L
labels: [memory, migration, scheduler, staggering, gitignore, fleet]
task-type: feature
parent-trdd: TRDD-87935f21
relevant-rules: []
release-via: publish
delivery: direct-push
test-requirements: [unit]
external-refs: []
---

# TRDD-3f7b6807 — Daily memory-system migration (staggered)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-20

- **USER request (2026-06-20):** complete the memory migration to the new
  (memgrep-managed / wikimem) system as a PERMANENT BACKGROUND chore running once
  per day; STAGGER per project (different time-of-day) to avoid rate-limit
  clustering; USER-scope work is shared so any project's agent may do it;
  LOCAL/PROJECT work needs the OWNING project's session; the scripts must ensure
  PROJECT-scope memory is git-TRACKED via a `.gitignore` EXCEPTION (never
  `git add -f`).
- **USER decisions (AskUserQuestion, 2026-06-20):** (1) **Enhance the existing
  harvest pass — NO new marker** (avoids re-arm rollout lag); add staggering +
  ship the gitignore enforcer as a standalone detector. (2) **Build + RUN the
  migration on THIS project now.**
- **KEY FINDING — the migration is half-built + already LIVE.** The 5 editor
  passes were re-enabled this session (v0.13.0). Harvest (1/day) IS the core
  migration (MEMORY.md → deprecation stub + incorporate stray notes). Repair
  (3/day) backfills page shape (ran once already — 5 LOCAL pages). The scheduler's
  MACHINE-WIDE dispatch flock ALREADY bounds editor load to ≤1 pass per ~5-min
  window machine-wide (baseline rate-limit protection). Scope ownership already
  matches the spec (LOCAL=owning session, USER=any project flock-deduped,
  PROJECT=owning repo staged-not-pushed).
- **THE 3 GAPS to close (this TRDD):**
  1. **Per-project PHASE staggering** — `memory_settings.is_due` is pure interval
     (`now-last_run ≥ interval`); add a deterministic per-(project,intervention)
     phase offset (from `sha256(root:intervention)`) so daily sweeps spread across
     the day instead of clustering on day-1. Behind `stagger_enabled` (default on).
  2. **PROJECT-memory gitignore-exception ENFORCER** — a lib + heartbeat detector
     that guarantees `<repo>/.claude/project/memory/` is tracked via the `!`
     exception (adds `!.claude/project/` + `!.claude/project/memory/` +
     `!.claude/project/memory/**` when `.claude/` is ignored), idempotent, atomic,
     NEVER `git add -f`.
  3. **Run the migration NOW on this project** — harvest LOCAL `MEMORY.md` → stub;
     finish repairing the 14 remaining malformed LOCAL pages.
- **USER-scope division:** the existing scheduler already lets ANY project service
  USER (round-robin + flock-dedup); the staggering spreads WHICH project does USER
  WHEN. No sharding code this TRDD (optional future enhancement) — the spec's
  "may divide" is satisfied by the existing any-project-can-do-USER design.
- **PROGRESS (2026-06-20):** P1 (staggering — `is_due` phase-aligned + `stagger_enabled`,
  7 tests) DONE+committed. P2 (gitignore enforcer `project_memory_tracked.ensure_tracked` +
  `project-memory-tracked` detector + dispatch register, 6 tests, never `git add -f`)
  DONE+committed. P3a (LOCAL `MEMORY.md` → stub, harvest_preservation_ok PRESERVED,
  backup kept, reindexed) DONE. P3b (repaired ALL 19 malformed LOCAL pages → 0 remain;
  every commit verify_repair-gated) DONE. 119 tests green, ruff clean.
- **NEXT ACTION:** (1) ship — Phases 1+2 are working-tree only; they reach the live cache
  via the next `publish.py` + daemon roll. (2) PROJECT-scope migration is SEPARATE and
  NEEDS A USER CALL: the PROJECT `MEMORY.md` is a shared/pushed curated 28-line index;
  retiring it to a stub per the new model requires first harvesting its navigation into a
  `<repo>-overview.md` entry page (the user's overview-page concept) — surfaced, not done.

## Design — map requirements → components

| USER requirement | How it is met |
|---|---|
| daily migration, permanent, background | the existing harvest pass (harvest_per_day=1), re-enabled v0.13.0 — the daily anchor |
| different time per project (rate limits) | **NEW** per-(project,intervention) phase offset in `is_due` (Phase 1) + the existing machine-wide flock (already serializes to ≤1 pass/5min) |
| USER-scope divisible across projects | existing: any project services USER (scheduler round-robin + flock-dedup) |
| LOCAL/PROJECT need the owning project | existing: LOCAL resolves from `pwd`, PROJECT from the repo's git-root — only that project's session resolves them |
| PROJECT memory git-tracked via gitignore exception, never force-add | **NEW** enforcer lib + detector (Phase 2) |
| "complete" the migration | **RUN NOW** on this project (Phase 3) |

## Phases (≤5 files each; verify + commit between)

- **P1 — staggering.** `scripts/lib/memory_settings.py`: add `stagger_enabled`
  (bool, default True) + a phase-aligned `is_due` (`phase =
  sha256(f"{root}:{intervention}") % interval`; due when `now` has crossed a
  phase-aligned `k*interval+phase` boundary since `last_run`). First-run
  (last_run=0) still fires promptly (flock serializes day-1); steady state aligns
  to the project's slot. Unit tests: two roots get distinct phases; same root
  stable; disabled → falls back to plain interval; disabled-rate (0) still never
  due.
- **P2 — gitignore-exception enforcer.** `scripts/lib/project_memory_tracked.py`
  (`ensure_tracked(repo_root) -> (action, detail)`: no-op when the memory dir is
  absent or already un-ignored; else append the 3 exception lines idempotently +
  atomically; NEVER `git add -f`) + `scripts/detectors/project-memory-tracked.py`
  (heartbeat detector, project-scoped, emits a drift line only when it added the
  exception or memory is still untracked) + register in `dispatch.py` roster.
  Unit tests on temp git repos: ignored→exception-added→tracked; already-fine→no-op;
  no-`.gitignore`→created-with-exception; never force-add.
- **P3 — run now on this project.** Harvest LOCAL `MEMORY.md` → stub (via the live
  harvest path / txn core); finish repairing the 14 malformed LOCAL pages; reindex.
  (USER already clean; PROJECT already tracked.)
- Each phase: `uv run scripts/publish.py`-grade gates locally (pytest + ruff +
  CPV `--strict`) before the change is considered done; commits ride the next
  publish (pre-push hook).

## Acceptance

- Two projects' daily harvest become due at DISTINCT times-of-day (staggering
  proven by a unit test on `is_due` phase offsets); `stagger_enabled=off` restores
  plain-interval behavior.
- A repo whose `.claude/` is gitignored gets the `!.claude/project/memory/**`
  exception added (its memory becomes tracked) with NO `git add -f`; an
  already-compliant repo is a no-op; the detector surfaces the one-time fix.
- This project's LOCAL `MEMORY.md` is the deprecation stub; 0 malformed LOCAL pages
  remain; memgrep recall over LOCAL is fresh.
- All unit tests green; CPV `--strict` exit 0; shipped via publish.

## Notes

- Distinct from TRDD-47df698b (task #209 — re-scope the ai-maestro 72-file corpus
  LOCAL→PROJECT). THIS is the format/system migration (MEMORY.md→stub + page-shape),
  daily + staggered. They share the memory_scopes SSOT.
- Lessons captured to the wiki as encountered (USER directive 2026-06-20: learn
  from every issue, improve the memory system) — e.g. the zsh `UID`-readonly gotcha
  hit while authoring this TRDD.
