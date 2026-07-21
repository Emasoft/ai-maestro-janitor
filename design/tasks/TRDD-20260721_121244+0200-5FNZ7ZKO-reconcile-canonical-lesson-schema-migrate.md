---
trdd-id: 5FNZ7ZKO
title: reconcile the ONE canonical lesson-atom schema and migrate the 153 lean lessons
column: blocked
pre-block-column: todo
blocked-by: [R02HTRUD]
created: 2026-07-21T12:12:44+0200
updated: 2026-07-21T12:12:44+0200
current-owner: claude-ai-maestro-janitor
task-type: refactor
scope: project
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-21

**BLOCKED on [[TRDD-R02HTRUD]]** — settle the canonical form the writer emits FIRST, then fix the
docs to match it, then migrate. When A1 lands, restore `column: todo`.

**NEXT ACTION:** ratify ONE canonical lesson/atom schema, then (1) fix the 3 governing docs, (2)
migrate the ~153 lean lessons to it via the verify-gated subconscious agent.

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
