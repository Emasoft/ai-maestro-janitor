---
trdd-id: ab232dbd-59eb-4bff-8770-4dd7c65ac00e
title: MEMORY.md buffer ⇄ Wikimem wiki coexistence — harvest-mirror, never stub
column: dev
created: 2026-06-23T10:58:37+0200
updated: 2026-06-23T11:28:38+0200
current-owner: claude-janitor-dev
assignee: claude-janitor-dev
task-type: refactor
priority: 0
severity: HIGH
effort: L
labels: [memory, wikimem, harvest, architecture, recall-rule]
parent-trdd: TRDD-87935f21
supersedes: []
relevant-rules: []
release-via: publish
test-requirements: [unit]
external-refs: ["github.com/Emasoft/ai-maestro-janitor/issues/60"]
---

# MEMORY.md (buffer) ⇄ Wikimem (wiki) coexistence — harvest mirrors, never stubs

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-23

### USER DIRECTIVE (verbatim, 2026-06-23 ~10:50)
*"there is an urgent issue with the MEMORY.md system. I told you to empty it and leave only
a reference to the wikimem skills. But I realized that Anthropic is continuously growing the
memory.md system, and the latest version of CC is making changes too. So let's go back to the
original approach we took: coexistence of both systems and cooperation/integration with each
others. So the MEMORY.md system and the Wikimem system will coexist as separate things: one is
a memory system (unorganized buffer), the other is a curated wiki, with rich metadata, notes,
git versioning and bidirectional linking between pages. Both the MEMORY.md and the Wikimem must
live in parallel, and the janitor chores must include a harvest chron that will find newly
created memories and add them to the wiki in a curated, metadata rich format."*

### THE PRECISE REVERSAL (grounded in TRDD-a5780c23, the v0.13.0 deprecation pivot)
a5780c23 retired MEMORY.md to a deprecation stub because it was *"a REDUNDANT janitor-maintained
index that grows + gets trimmed"* (the manual-trim corruption). The NEW realization corrects the
premise: **MEMORY.md is NOT the janitor's index — it is Anthropic's NATIVE buffer** (the harness
`# Memory` directive writes it + auto-loads it every session; CC keeps evolving it). So:
- **KEEP** a5780c23's valid insight: memgrep is the unlimited, agent-invisible index FOR THE WIKI;
  the janitor never hand-maintains an index (that caused the corruption).
- **REVERSE** only the "stub/retire MEMORY.md" decision: the janitor stops stubbing/trimming it,
  lets the harness own it, and **HARVESTS from it** into the curated wiki.

### THE COEXISTENCE MODEL (the target)
- **MEMORY.md = the BUFFER** — Anthropic/harness-owned, unorganized, grows freely, auto-loaded
  each session. The janitor READS it as a harvest source; it NEVER stubs/trims/maintains it.
- **Wikimem = the WIKI** — curated pages: rich frontmatter (`ocd`/`lmd`/tier), `[^N]` lessons,
  bidirectional links, git-versioned, memgrep-indexed (unlimited, agent-invisible).
- **Harvest cron = the BRIDGE** — incrementally finds NEWLY-created buffer memories and MIRRORS
  them into the wiki in curated, metadata-rich form. Additive, non-destructive, buffer left intact.

### CORE BEHAVIORAL CHANGE
The harvest skill's step 5 ("reduce MEMORY.md to the stub") is DELETED. Harvest goes from
"re-file strays then RE-STUB" → "incrementally MIRROR new buffer memories into the wiki, leave
MEMORY.md 100% intact." Everything else about the editorial curation (step 3) is preserved.

### TOUCHPOINTS (the reversal surface — >5 files → parallel agents, TDD, NO bursts)
1. `rules/markdown-memory-recall.md` *(HIGHEST IMPACT — global, every session)* — rewrite the
   "MEMORY.md DEPRECATED / retired / don't add pointers / index retired" sections → the
   coexistence model. KEEP the "memgrep = unlimited agent-invisible WIKI index" part.
2. `skills/janitor-memory-harvest/SKILL.md` — drop the re-stub (step 5); incremental mirror +
   a per-scope harvest watermark; leave MEMORY.md intact. Update the description.
3. `skills/janitor-memory-{write,bootstrap,split,consolidate}/SKILL.md` — un-deprecate MEMORY.md
   wording; bootstrap stops seeding the stub.
4. `scripts/lib/memory_edit_verify.py::harvest_preservation_ok` — now confirms the MIRROR is
   complete (every buffer memory is in a wiki page); it no longer gates a stub reduction.
5. `scripts/detectors/memory-librarian.py` (#55) — keep the "don't flag notes missing from
   MEMORY.md" retirement (the buffer is NOT the wiki's index — still correct), but re-confirm.
6. `scripts/memgrep/src/memory.rs` — keep memgrep as the WIKI index; reconsider any MEMORY.md
   special-casing (see fork Q1).
7. `scripts/lib/memory_settings.py` — `harvest_per_day` (reuse; default stays 1); the watermark
   store (new).
8. The MEMORY.md stub content — the janitor stops WRITING the deprecation stub anywhere.
9. README / CLAUDE.md docs — the coexistence story.

### DERIVED TASKS (consequences to handle)
- **Harvest must be incremental + idempotent** — a watermark so it never re-mirrors the same
  buffer memory (else duplicate wiki pages). Crash-safe (the txn core).
- **Buffer-vs-wiki discrimination** — both live in the same scope dir; harvest must tell a raw
  buffer note (minimal/no wikimem frontmatter) from a curated wiki page (rich tier/ocd/lmd) so
  it harvests only un-curated buffer entries, not re-process wiki pages.
- **De-dup on mirror** — a buffer memory whose subject already has a wiki page → UPDATE that page
  (correction protocol), don't create a duplicate. (RECALL-before-write inside harvest.)
- **The reload lag** — the recall-rule change only reaches sessions after rules_installer re-runs
  (SessionStart) + the heartbeat re-arm; note the rollout.
- **Reverse, don't lose** — the old deprecation lessons (a5780c23) are demoted, not deleted.

### RESOLVED ARCHITECTURE — USER decision 2026-06-23 ("Separate parallel copies")
The USER chose **separate parallel copies** over promote-in-place: harvest NEVER modifies a raw
buffer note (harness-owned); it creates a SEPARATE curated copy in a `wiki/` sub-namespace; the
same fact lives in BOTH files (duplication accepted); a watermark tracks what's mirrored.

**Grounding fact (verified 2026-06-23 on this machine's LOCAL+PROJECT scopes):** EVERY existing
`memory/*.md` already carries FULL wikimem frontmatter (`node_type: memory` + `ocd`/`lmd`/`tier`)
— even the type-prefixed `feedback_*`/`reference_*`/`project_*`/`local_*` notes. There are **ZERO
raw buffer notes physically present** right now: the old in-place model curated everything, and
MEMORY.md is the 548-byte deprecation stub. So the buffer is currently **dormant** — the harvest
does NOTHING to the current corpus (all already curated); it ACTIVATES when the harness next
writes a minimal-frontmatter note. This dissolves the migration risk: **no bulk move is needed.**

**The physical layout (per scope — LOCAL `~/.claude/projects/<slug>/memory/`, PROJECT
`<repo>/.claude/project/memory/`, USER `<plugin-data>/…/memory/`):**
- **Buffer** = `memory/*.md` TOP-LEVEL + MEMORY.md — harness-owned, minimal frontmatter, grows
  freely, auto-loaded each session. Harvest READS it; NEVER writes/trims/stubs it.
- **Wiki** = `memory/wiki/*.md` — the curated layer's home GOING FORWARD (rich frontmatter, `[^N]`
  lessons, bidirectional links). Harvest + the write/split/consolidate/conflict/repair skills
  write HERE.
- **Discriminator (frontmatter shape, NOT path):** a page with `metadata.tier` / `node_type:
  memory` is CURATED (skip in harvest); a minimal note (no tier) is RAW BUFFER (harvest it). The
  current full-frontmatter top-level pages are LEGACY curated — recallable + de-dup'd against;
  their optional relocation into `wiki/` is a SEPARATE deferred tidy-up (not this ship).

**Q1 — recall scope: RESOLVED.** memgrep recall stays UNCHANGED — it recurses `memory/`, so it
naturally covers BOTH the top-level buffer notes (closing the pre-harvest recall gap) AND the
`wiki/` curated pages. The harness additionally auto-loads MEMORY.md. No memgrep change; no
recall gap.

**Q2 — harvest tracking: RESOLVED.** A per-scope watermark (name + content-hash of each mirrored
buffer note) → harvest only the un-mirrored delta, idempotent + crash-safe via the txn core.
Buffer left 100% intact. **De-dup:** before mirroring a buffer note, RECALL its subject across
`wiki/`; if a page exists → UPDATE it (correction protocol); else CREATE `wiki/<name>.md`.

### PUBLISH INTERACTION
This REVERSES part of the unpublished v0.16.0 memory work (the stub/deprecation model). It folds
into the publish — the v0.16.0 (or v0.17.0) release now ships coexistence, not deprecation. The
publish stays paused (also still blocked on the immortality-persistence decision — see
TRDD-fe45babc §1).

### NEXT ACTION (architecture DECIDED — implement)
1. ✅ Phase 1a — recall rule coexistence rewrite (committed 61ca557). Refine: memgrep recalls the
   whole `memory/` tree (buffer + `wiki/`); name the `memory/wiki/` namespace explicitly.
2. **Phase 1b (NOW)** — `memory_scopes.py`: add `resolve_wiki_dir()` per scope (`memory/wiki/`) +
   tests. Then rewrite `skills/janitor-memory-harvest/SKILL.md`: scan top-level RAW buffer notes
   (minimal frontmatter) NOT yet watermarked → RECALL across `wiki/` → UPDATE-or-CREATE
   `wiki/<name>.md` → stamp watermark; DROP the step-5 re-stub; leave MEMORY.md + buffer intact.
3. Phase 1c — write/bootstrap/split/consolidate/conflict/repair skills target `memory/wiki/` for
   the curated layer; bootstrap creates `wiki/` + stops seeding the stub. `memory_settings.py`
   watermark store. `harvest_preservation_ok` confirms the MIRROR (not a stub reduction).
4. Phase 1d — README / CLAUDE.md coexistence story; detectors re-confirm (#55).
5. DEFERRED (separate careful task): relocate LEGACY full-frontmatter top-level pages → `wiki/`
   (PROJECT via git mv is safe; LOCAL via backup-first). NOT required for this ship.
6. Fold into the publish (still paused — also blocked on immortality-persistence, TRDD-fe45babc §1).

## Notes and lessons learned
