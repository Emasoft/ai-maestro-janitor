---
trdd-id: 5FNZ7ZKO
title: reconcile the ONE canonical lesson-atom schema and migrate the 153 lean lessons
column: complete
created: 2026-07-21T12:12:44+0200
updated: 2026-07-21T14:25:00+0200
current-owner: claude-ai-maestro-janitor
task-type: refactor
scope: project
implementation-commits: [6f9d818]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-21

**SHIPPED (6f9d818, 2026-07-21) — migration complete, prose independently verified LOSSLESS.**
153 lean lessons → 0 across all 3 scopes (USER 70 / PROJECT 53 / LOCAL 30), backfilled to the
ratified 5-key `[id:ATOM-…, status:valid, keywords:"…", ocd:…, lmd:…]`. Verified NOT by the
agent's self-report but by my own line-diff oracle: across all 67 backed-up files the ONLY changed
lines are `[^N]` lesson headers whose metadata bracket expanded — every prose/body/`^atom`/
frontmatter line byte-identical; post-migration `wikimem_syntax_lint` = 0 lean lessons. Only the 19
PROJECT files are git-tracked (this commit); USER (34) + LOCAL (14) migrated in place (not a repo).
Schema-doc reconciliation (part 1) landed via [[TRDD-6RO0L3M0]] (skills now call `add-lesson`, which
emits the 5-key form by construction) + the RULE already carried it. **NEXT ACTION:** none —
awaiting end-of-run sweep → `complete`.

**FOLLOW-UP (out of scope — NOT a regression):** 4 pre-existing `atom-dup-id` CRITICALs are
cross-scope page mirrors (same feedback note in USER+LOCAL: `feedback_memory_dual_test_evaluation`,
`feedback_security_act_dont_ask`, `feedback_head_tee_sigpipe`). Untouched by this migration (zero
`^atom` line changes proven). Resolving them is a scope-routing dedup decision for a separate
memory-curation pass, surfaced by [[TRDD-VPTQ4067]]'s detector.

**SUPERSEDED — do NOT carry forward:** the earlier "confirm the schema with the owner before
migrating" step — the owner delegated authority 2026-07-21 and ratified the 5-key form; migration is
done.

## Problem — three conflicting schemas produced corpus drift

Verified 2026-07-21:
- `skills/janitor-memory-write/SKILL.md:144` → lesson `[keywords, desc, ocd, lmd]` (4-key)
- `skills/janitor-memory-update/SKILL.md:125` → lesson `[keywords, ocd, lmd]` (3-key)
- `~/.claude/rules/markdown-memory-recall.md` → lesson `[id, status, keywords, ocd, lmd]` (5-key)

Result (measured by `wikimem_syntax_lint.py`): **153 lean lessons** (`[ocd: lmd:]`-only, no id, no
keywords) — un-recallable by symptom, no stable id. USER 70 · PROJECT 53 · LOCAL 30.

## Approach

1. **Ratify ONE form.** RECOMMEND the RULE's 5-key `[id:ATOM-…, status:valid|superseded,
   keywords:"…", ocd:…, lmd:…]` — `keywords` = recall surface, `id` = stable corpus reference that
   survives `[^N]` renumbering, `status`/`superseded-by` = the supersession mechanism. This is a
   governance decision — confirm with the owner before migrating (a schema is a project convention).
2. **Fix the docs** so all three specify the SAME form: the two skills + the block-properties memory
   page. [[TRDD-R02HTRUD]]'s `add-lesson` emitter then produces exactly this form by construction.
3. **Migrate the 153 lean lessons** via `janitor-memory-subconscious-agent` (a repair/atomize-class
   pass): backfill `id` + `keywords` from each lesson's prose, PRESERVING every word. Its
   `memory_edit_verify` oracle (`lessons_preserved`, `fact_tokens_preserved`) PROVES no prose lost.

## Derived tasks

- The migration must NOT invent keywords — derive them from the lesson's own prose (the DO-NOT/BECAUSE
  subject), and flag any lesson whose keywords are ambiguous for human review.
- Per-scope: LOCAL (30) + PROJECT (53) are this repo's; USER (70) is global — migrate all three roots.
- RULE 0: commit each scope's migration before any cleanup; the subconscious agent's txn is crash-safe.

## Verification

Post-migration `memgrep lint` ([[TRDD-VPTQ4067]]) reports **0 lean lessons**; the subconscious
verifier proves no prose lost (diff each lesson's prose survives verbatim); the 3 docs specify ONE
identical form (grep all three → same key list). `uv run pytest` + `ruff check` green.

## Notes and lessons learned
