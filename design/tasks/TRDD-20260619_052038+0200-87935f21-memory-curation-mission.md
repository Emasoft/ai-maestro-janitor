---
trdd-id: 87935f21-392a-4022-8161-64f493663c44
title: Memory curation at all scopes — the janitor's core self-maintaining mission
column: dev
created: 2026-06-19T05:20:38+0200
updated: 2026-06-19T12:32:00+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 1
severity: HIGH
effort: XL
labels: [memory, wikimem, memgrep, librarian, autonomous, mission]
task-type: feature
parent-trdd: TRDD-54b25d7e
relevant-rules: []
release-via: publish
test-requirements: [unit]
external-refs: []
---

# TRDD-87935f21 — Memory curation is the janitor's core mission

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-19

- **Mandate (USER, 2026-06-19, verbatim intent):** "fixing memories, at all
  levels (user, project, local) IS the main activity of the janitor!" Not just
  fix them once — **build skills + scripts so the janitor identifies & fixes
  these issues automatically, on an agent-intelligence cadence (a few times/day).**
  These 6 priorities are STANDING (now and always, automatically).
- **The 6 standing priorities (in order):**
  1. Identify and fix all **memgrep** bugs.
  2. Identify and fix all **memory helper script** bugs.
  3. Identify what causes **bad wikimem pages** → fix/improve the **3 memory
     skills** + all their script helpers.
  4. Identify all **bad wikimem pages** → fix them (broken/wrong refs,
     unreachable/undiscoverable memories, missing metadata + Notes sections).
  5. Identify shortcomings of the **consolidation** phase/skills → improve them
     to keep **Wikipedia-like editing quality** across all memory.
  6. Ensure the **background machinery runs error-free on ALL armed projects**,
     that Claudes are **nudged to memorize recent changes**, and that the
     **WHY-in-commit-messages** rule is honored.
- **PROGRESS:** P1 (memgrep `.`-contamination + walk_and dedup), P2 (helper
  flow-style `metadata` parse + 2 LOW), P3 (3 skills — PROJECT scope routing +
  tier/metadata enforcement + clean memgrep cmd), and P4 (the autonomous repair
  pass — `verify_repair` + txn `--op repair` + `repair_per_day` + the
  `[janitor-memory-repair]` marker + skill) all SHIPPED in **v0.11.0**. **P6 (this
  session):** P6.2 memorize-nudge detector (`memorize-nudge.py`, d14510a) + P6.3
  why-in-commits detector (`why-in-commits.py`, aa4c593) + the shared
  `memory_scopes.py` SSOT refactor (10ee8d1, dedups the LOCAL/PROJECT/USER
  resolvers out of memory-maintenance + memory-librarian) — all DONE, tested
  (subprocess-based, hermetic), ruff-clean, full `tests/` suite 11118 green. **P6.1
  (machinery self-audit) consciously SKIPPED** — it reduces to "is memgrep on PATH",
  already handled by graceful grep-fallback + the recall rule; a heartbeat nudge
  there would risk nagging for marginal value. P6.2+P6.3 ship in the next publish.
- **NEXT ACTION:** P5 — strengthen the consolidation (`janitor-memory-consolidate`)
  + `memory-librarian` passes for Wikipedia-grade one-topic-per-page structure
  (judgment-heavy, mostly skill prose). The EXISTING ai-maestro corpus migration
  (LOCAL→PROJECT) still awaits the USER's a/b/c choice — skill-independent. New
  detectors are dormant in THIS session until the daemon rolls the cache forward
  (or /reload-plugins) — they're verified via their tests + a live working-tree run.
- **Load-bearing finding (memgrep):** the documented filter command in
  `wikimem-model.md` / the recall rule — `memgrep -l . <dir> --where '…'` — is
  WRONG: the `.` is parsed as a second search PATH (= cwd), silently
  contaminating results with any memory files in the current directory. Correct
  form: `memgrep -l <dir> --where '…'` (no `.`). Verified 2026-06-19.

## Background

The v0.10.0 wikimem editor (TRDD-54b25d7e + A–G) shipped the autonomous
split/merge/conflict passes. The USER then audited the **ai-maestro fleet
Claude's** real output (the 72-file LOCAL corpus at
`~/.claude/projects/-Users-emanuelesabetta-ai-maestro/memory/`) and found the
skills do NOT reliably enforce the model. This TRDD elevates memory curation to
the janitor's core, self-maintaining mission and tracks the program.

## Audit findings (evidence — the ai-maestro 72-file corpus, 2026-06-19)

1. **Scope mis-routing (worst structural error).** ALL project-structure pages
   (5 hubs frontend/backend/security/install/plugins; aspects amp-comm-graph,
   governance-r26-r40, agent-first-architecture; components; ~30 `project_*`
   notes) live in **LOCAL** scope. They describe the project's architecture →
   they must be **PROJECT** scope (git-tracked, shipped, survives a clone). There
   is currently NO PROJECT-scope memory dir for ai-maestro at all. Root cause:
   harness `# Memory` defaults to LOCAL + "UNSURE → LOCAL"; the write skill never
   actively routes architecture/code topics to PROJECT.
2. **Metadata incompleteness.** Of 70 pages: 58 missing `ocd`+`lmd`, 58 missing
   `tier`, 55 missing `node_type`, 55 missing the mandatory `## Notes and lessons
   learned` section, and **3 have NO frontmatter at all**. Only ~15 carry the
   full model — the schema was enforced only on the conscious "wiki page" path.
3. **memgrep findability.** (a) Frontmatter-less pages are invisible to `recall`
   (it ranks on description+title+tags only) — 2/3 tested unreachable via recall
   (`find`, which scans bodies, still reaches them). (b) The documented `--where`
   filter command is cwd-contaminating (the stray `.` — see STATE).
4. **Tier/type inversion (expand vs reduce).** 3 of 4 `aspect` pages
   (amp-comm-graph, agent-first-architecture-hub, plugin-two-worlds) have
   `## Governed by` (RECEIVE) but NO `## Applies to` (RADIATE) — built like
   components. An aspect is a *sun* that must radiate. The skill didn't enforce
   "aspect ⇒ `## Applies to`; component ⇒ `## Governed by`, never Applies-to".
   Plus a naming inconsistency (`agent-first-architecture-hub` typed `aspect`).

## Plan — two tracks, run together

### Track A — fix the concrete bugs NOW (audit-driven, evidenced)

- **memgrep (priority 1):** correct the filter command in `wikimem-model.md` +
  `~/.claude/rules/markdown-memory-recall.md` (drop the cwd-contaminating `.`).
  Audit the memgrep crate for further real bugs (recall body-fallback for
  frontmatter-less pages; `--where` path/pattern ambiguity UX). Ship with tests.
- **helper scripts (priority 2):** audit `memory_txn_cli.py`,
  `memory_settings*.py`, `user_mem_lib.py`, the verify lib, the detectors for
  bugs; fix with tests.
- **3 skills (priority 3):** `janitor-memory-write` / `-update` / the
  consolidate/split/conflict executors + `wikimem-model.md` —
  (a) make **scope routing a decisive first step** (project structure → PROJECT;
  machine-specific → LOCAL); (b) **MANDATORY full frontmatter + Notes section on
  every write** (no atomic-note escape hatch); (c) enforce **aspect⇒Applies-to /
  component⇒Governed-by**; (d) reinforce the link law (bidirectional).

### Track B — make it self-maintaining (the autonomous machinery)

- **Page-shape / metadata-repair pass (priority 4, NEW):** a 4th autonomous
  editor pass (sibling of split/merge/conflict) that the scheduler fires a few
  times/day: backfills missing `ocd`/`lmd`/`node_type`/`tier`/Notes-section,
  fixes inverted Applies-to/Governed-by, repairs broken/one-sided `[[links]]`,
  re-homes mis-scoped pages (surfacing cross-scope moves for human/agent OK), and
  makes every page recall-findable. Runs through the TRDD-A transaction core.
- **Consolidation quality (priority 5):** strengthen the merge/librarian passes
  so aggregation keeps one-topic-per-page, Wikipedia-style structure.
- **Background-machinery health + nudges (priority 6):** a self-audit that the
  heartbeat runs to prove the memory machinery works on EVERY armed project; a
  reliable nudge for Claudes to memorize recent changes; enforce WHY-in-commits.

## Acceptance

- memgrep + helper bugs fixed with tests; CPV `--strict` green; published.
- The 3 skills enforce scope + full metadata + correct tier structure (a sample
  authored under the improved skill passes the audit, memgrep finds it).
- The autonomous repair pass closes the audit gaps on a fixture corpus and is
  bounded/disable-able/crash-safe like the other passes.
- The heartbeat self-audit reports memory-machinery health per armed project.

## Notes

- The EXISTING ai-maestro corpus migration (LOCAL→PROJECT) touches ANOTHER
  project's store — pending the USER's a/b/c choice; the janitor fixes here are
  scope-independent of that migration.
