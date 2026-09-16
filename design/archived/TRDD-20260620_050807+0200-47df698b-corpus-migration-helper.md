---
trdd-id: 47df698b-d946-4c53-9ce4-d40d1b76a1d4
title: Memory scope-migration helper — re-scope LOCAL to PROJECT (ai-maestro corpus, option b)
column: published
implementation-commits: [4aa8613, ea5fae3]
created: 2026-06-20T05:08:07+0200
updated: 2026-08-02T06:33:00+0200
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

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-11

**2026-07-11 — PHASE 2 (`--apply`) IS BUILT.** The tool is now complete; what remains
is not janitor work.

`--apply --plan <plan.md>` publishes the plan's PROJECT-bound notes into
`<repo>/.claude/project/memory/`. Apply is publish-AND-retire — PROJECT scope is
git-tracked and PUSHED (a leak cannot be un-pushed), and the LOCAL original is the only
copy that exists — so it is guarded like the cookie scrub: prove first, mutate second.
Four guards, all fail-CLOSED, all refusing BEFORE anything is written:

1. **OWNERSHIP** — `--apply` refuses unless the cwd's git repo IS `--project-repo`.
   **There is deliberately NO bypass flag.** The TRDD's original sketch allowed "an
   explicit opt-in flag"; I rejected that. A switch that lets one project's session
   mutate another project's store is precisely the thing the cross-project rule exists
   to prevent, and an escape hatch on the only guard enforcing it is worth less than the
   guard. The owning Claude runs the tool from its own repo — which IS the contract.
2. **THE REVIEWED PLAN** — apply consumes the plan file and re-classifies to prove the
   corpus still classifies as the reviewer saw it. Any drift (a note edited, added, or
   gone since the dry-run) aborts: what was reviewed must be what is applied.
3. **PRIVACY RE-GATE** — every note about to be published is re-scanned AT APPLY TIME.
   One leak aborts the whole run. The plan's verdict is never trusted as a cache.
4. **VERIFY-THEN-RETIRE** — copy + byte-verify every destination BEFORE any source is
   touched, so a failure can never leave a half-migrated corpus. The source is then
   MOVED to the repo's gitignored `.trashcan/migrate-memory-scope/<ts>/` — never `rm`-ed
   (RULE 0: it is human-authored work outside any git repo). Recovery is one `mv`.
   `--keep-source` copies without retiring. A name collision in PROJECT scope refuses
   outright; apply never overwrites someone else's note.

Also wires `project_memory_tracked.ensure_tracked()` so the published scope is actually
git-TRACKED (a corpus published into a gitignored dir would be shared with nobody), and
writes an `…-applied.md` report next to the plan.

**Verified end-to-end through the real CLI** (throwaway repos): dry-run classified a
clean note → PROJECT and a `/Users/…`-bearing note → LOCAL (privacy gate held); apply
from the WRONG repo was REFUSED; apply from the OWNING repo published the clean note,
left the private one in LOCAL, and retired the source recoverably. 27 tests in
`test_memory_migrate.py` (10 new, all guards proven to refuse without mutating); ruff
clean.

**NEXT ACTION — NOT janitor work.** The ai-maestro corpus migration is the OWNING
project's Claude's job: it runs the dry-run, reviews the plan, then runs `--apply` in
its OWN session. This janitor session must NOT run `--apply` against
`~/.claude/projects/<ai-maestro-project-slug>/memory` — that is exactly the
cross-project mutation the guards refuse.

**SUPERSEDED — do NOT carry forward** (the `### The tool` sketch further down predates
the shipped build):

- *"update BOTH `MEMORY.md` indexes"* — OBSOLETE. `MEMORY.md` is now a deprecation STUB;
  the index is 100% memgrep's (`markdown-memory-recall.md`: "do NOT add pointers here").
  Writing index entries would re-create the hand-maintained index that rule retired.
- *"redirect cross-scope `[[backlinks]]`"* — UNNECESSARY. A wiki link is `[[slug]]`, the
  slug does not change on a move, and recall composes all three scopes in one query — so
  a link into a migrated note still resolves. There is nothing to rewrite.
- *"idempotent (re-run = no-op once migrated)"* — CHANGED, deliberately. A re-run of the
  same plan now REFUSES ("in the plan but no longer in the corpus"), because the notes
  were retired from LOCAL. A silent no-op is indistinguishable from a successful apply;
  a loud refusal tells the operator the truth.
- *"(or an explicit opt-in flag)"* on the ownership guard — REJECTED (see guard 1 above).

**2026-07-04 board-reconciliation (TRDD-GB3Z9U9J):** Phase 1 (read-only classifier + reviewable plan) shipped — `scripts/migrate_memory_scope.py` + `scripts/lib/memory_migrate.py` in-tree.

### 2026-08-02 — CLOSED (`dev → published`). Phase 2 shipped too; the rest is another project's session.

The 2026-07-04 note above stopped at Phase 1, which is why this stayed in `dev` for four weeks —
but **Phase 2 landed as well** (`ea5fae3`, `memory_migrate.apply_plan`, 27 tests in
`tests/test_memory_migrate.py`), and both it and the Phase-1 classifier (`4aa8613`) are contained
in the released tag `ai-maestro-janitor--v0.45.0`. Verified by reading the module and running the
tests, not from the card.

**What this card promised is therefore delivered in full.** Its scope, fixed by the USER's
option (b) on 2026-06-20, is *write a migration helper the ai-maestro Claude runs* — a general
LOCAL→PROJECT re-scoping tool with the four fail-CLOSED guards. It never included performing the
ai-maestro corpus migration.

**The remaining step is not janitor work, by this card's own load-bearing contract**, which the
NEXT ACTION below states outright: the OWNING project's Claude runs `--apply` in ITS OWN session,
and this session must never run it against
`~/.claude/projects/<ai-maestro-project-slug>/memory` — that is exactly the cross-project
mutation the guards refuse, and `~/.claude/rules/how-to-fix-issues-of-other-projects.md` forbids
it independently. A card cannot stay open waiting for an action it is forbidden to take; holding
it in `dev` implied someone here was still going to do it.

`release-via: publish` + released ⇒ **`published`** (rule 12). `implementation-commits:` recorded.

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
  `~/.claude/projects/<ai-maestro-project-slug>/memory` = 70 real notes
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
