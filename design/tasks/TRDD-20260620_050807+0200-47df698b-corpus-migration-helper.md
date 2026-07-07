---
trdd-id: 47df698b-d946-4c53-9ce4-d40d1b76a1d4
title: Memory scope-migration helper — re-scope LOCAL to PROJECT (ai-maestro corpus, option b)
column: dispatch
created: 2026-06-20T05:08:07+0200
updated: 2026-07-04T05:14:00+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 2
severity: MEDIUM
effort: M
labels: [memory, wikimem, scope, migration, cross-project]
task-type: feature
parent-trdd: TRDD-87935f21
relevant-rules: []
release-via: publish
test-requirements: [unit]
external-refs: []
---

# TRDD-47df698b — Memory scope-migration helper (LOCAL→PROJECT)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-20

**2026-07-04 board-reconciliation (TRDD-GB3Z9U9J) — PARTIALLY SHIPPED, stays dispatch:** Phase 1 (read-only classifier + reviewable plan) is shipped — `scripts/migrate_memory_scope.py` + `scripts/lib/memory_migrate.py` in-tree; `--apply` still FAILS FAST by design (migrate_memory_scope.py:15-19) because Phase 2 (owning-Claude apply) is unbuilt and cross-project/USER-gated (fe45babc journal: "#209 needs the target corpus").

- **Origin:** the USER chose **option (b)** for the mis-scoped ai-maestro fleet
  corpus (2026-06-20): *write a migration helper the ai-maestro Claude runs* — NOT
  (a) skills-only (already done in P3) and NOT (c) I-migrate-directly (forbidden by
  `~/.claude/rules/how-to-fix-issues-of-other-projects.md` — never edit another
  project's store directly).
- **What ships:** a GENERAL janitor tool `scripts/migrate_memory_scope.py`
  (LOCAL→PROJECT re-scoping, conservative + privacy-first) + a thin skill wrapper.
  Reusable for ANY project's corpus; the ai-maestro corpus is the first consumer.
- **CROSS-PROJECT CONTRACT (load-bearing):** the JANITOR (this repo) only WRITES
  the helper. The OWNING project's Claude (ai-maestro) RUNS `--apply` in ITS OWN
  session. The janitor session does **read-only recon** of another store, NEVER an
  `--apply` against it. The helper enforces this — `--apply` refuses unless invoked
  for the store whose owning repo is the cwd (or an explicit opt-in flag).
- **Recon (2026-06-20, read-only):** corpus at
  `~/.claude/projects/-Users-emanuelesabetta-ai-maestro/memory` = 70 real notes
  (excl. `user-mem/` + generated). Owning repo `~/ai-maestro` exists; its
  `.claude/project/memory/` is **absent** (no PROJECT scope yet). `type:`
  distribution ≈ project 34, feedback 29, reference 7 (two frontmatter styles —
  some `type:` top-level, some under `metadata:` — the classifier must read both).
- **NEXT ACTION:** build the **read-only classifier** first (Phase 1 — safe), run it
  against the real corpus to emit the draft PLAN, hand the plan to the ai-maestro
  Claude for review. THEN Phase 2 (`--apply`, run by the owning Claude) + tests +
  ship. Do NOT build `--apply` to run against another store from here.
- **Load-bearing safety:** the classifier's PROJECT verdict MUST pass a privacy
  gate that REUSES the `memory-scope-leak` detector's patterns — a note with any
  machine-private datum (local abs path, hostname, username, credential hint) can
  NEVER go to PROJECT (which is git-tracked + PUSHED). UNSURE → LOCAL, always.

## Background

The ai-maestro fleet Claude's 72-file LOCAL corpus (TRDD-87935f21 audit) holds
project-structure pages — 5 hubs (frontend/backend/security/install/plugins),
aspects, components, ~30 `project_*` notes — in **LOCAL** scope. Project structure
is shared knowledge → it belongs in **PROJECT** scope (git-tracked, pushed,
survives a clone). The janitor's WRITE skill now routes future writes correctly
(P3), but the EXISTING corpus stays mis-scoped until migrated. The migration
touches another project's store, so it is done via a helper the owner runs.

## Design

### The tool — `scripts/migrate_memory_scope.py`

```
migrate_memory_scope.py <local-mem-dir> --project-repo <repo> [--dry-run | --apply]
```

- **`--dry-run` (DEFAULT, read-only):** scan every real note (reuse the split-fix
  exclusion — skip `user-mem/`, `MEMORY.md`, `memory-index.md`,
  `memory-reorg-proposed.md`, `.maint-staging/`), classify each, and write a
  reviewable PLAN to `reports/migrate-memory-scope/<ts>-plan.md`. NO mutation.
- **`--apply` (run by the OWNING Claude after review):** ensure
  `<repo>/.claude/project/memory/` exists + the gitignore exception
  (`!.claude/project/memory/**`); move each PROJECT-bound note there (preserve
  content + frontmatter, backfill missing `ocd`/`lmd`/`node_type` if trivially
  derivable); update BOTH `MEMORY.md` indexes; redirect cross-scope `[[backlinks]]`;
  print a summary. **Idempotent** (re-run = no-op once migrated). PROJECT commits
  ride the owning repo's publish/PR flow — the helper never `git push`es.

### Classification (conservative, privacy-FIRST)

For each note, decide PROJECT / LOCAL-stay / UNSURE:

1. **Privacy gate FIRST (hard).** Run the `memory-scope-leak` patterns over the
   note body+frontmatter. ANY machine-private datum (local abs path, hostname,
   username, IP, credential hint) ⇒ **LOCAL-stay**, regardless of topic. A note can
   only be PROJECT-bound if it is privacy-clean.
2. **Topic signal.** Privacy-clean AND (`metadata.type: project` OR tier
   hub/aspect/component OR filename `project_*`/hub/aspect-named OR the body is
   about architecture/code/conventions any contributor needs) ⇒ **PROJECT**.
3. **Machine/about-user signal.** `type: user`, filename `local_*`, or content that
   is about THIS machine/instance ⇒ **LOCAL-stay**.
4. **Everything else / ambiguous ⇒ UNSURE ⇒ LOCAL-stay** (the safe scope; the
   owning Claude can promote later). Mirrors the write-skill "UNSURE → LOCAL" rule.

The PLAN lists each note with its verdict, the deciding reason, and the
privacy-scan result, so the owning Claude reviews before `--apply`.

### Safety model

- Dry-run default; `--apply` reviewable + idempotent; privacy gate blocks private
  data from the PUSHED PROJECT scope; UNSURE→LOCAL; `--apply` refuses to run
  against a store whose owning repo is not the cwd (cross-project contract).
- Reuses the split-fix non-note/`user-mem` exclusion (ideally via the
  memory_scopes SSOT once TRDD-87935f21's next increment lands).

## Acceptance

- Classifier emits a correct PLAN on the 70-note corpus: project-structure pages →
  PROJECT, machine-specific → LOCAL, **zero** privacy-flagged notes in PROJECT.
- `--apply` (on a FIXTURE corpus) is idempotent, creates the PROJECT dir + gitignore
  exception, moves + re-indexes notes, redirects backlinks, never pushes.
- The janitor session only ever dry-runs another store; `--apply` against ai-maestro
  is run by the ai-maestro Claude.
- Unit tests on real fixtures (no mocks); CPV `--strict` green; shipped.

## Notes

- This is `release-via: publish` (a real janitor tool) — the helper + skill + tests
  ship in a janitor release; the ai-maestro Claude then runs it.
- Depends-soft on TRDD-87935f21's SSOT increment (the shared note-file exclusion);
  can land first with the inline exclusion and adopt the SSOT helper when it exists.
