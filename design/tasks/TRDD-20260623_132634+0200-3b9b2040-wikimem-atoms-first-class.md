---
trdd-id: 3b9b2040-42b1-4217-8268-d787b389fd05
title: Wikimem atoms as first-class index elements — block-properties parse/index/recall, harvest-into-atoms, prose→atom migration
column: design
created: 2026-06-23T13:26:34+0200
updated: 2026-06-23T13:26:34+0200
current-owner: claude-janitor-dev
assignee: claude-janitor-dev
task-type: refactor
priority: 0
severity: HIGH
effort: XL
labels: [memory, wikimem, memgrep, atoms, block-properties, indexing, recall, architecture]
parent-trdd: TRDD-87935f21
npt: []
eht: []
blocked-by: []
relevant-rules: []
release-via: publish
test-requirements: [unit, integration]
external-refs: ["github.com/Querulantenkind/obsidian-block-properties-plugin"]
---

# Wikimem ATOMS as first-class index elements (block-properties parse/index/recall + harvest-into-atoms + prose→atom migration)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-23

### WHY THIS TRDD EXISTS (the realization, USER-confirmed 2026-06-23)
While building the MEMORY.md⇄Wikimem coexistence harvest (TRDD-ab232dbd), the USER asked:
*"how then you managed to grep the atom memories before this, since without a metadata system
you simply cannot attach keywords to single atoms of memory… I'm shocked I realized this only
now."* Investigation (VERIFIED against `scripts/memgrep/src/index.rs` + `memory.rs`) confirmed:
**memgrep has NO atom-level metadata or recall. It indexes at PAGE + LESSON granularity only.**
The per-atom metadata model (the Obsidian Block Properties convention) was a SPEC that was never
wired into memgrep's indexer. So "recall an atom by its keywords" never worked — atoms were only
findable as part of their page. The USER chose **"Stop & redesign"**: pause implementation, write
THIS design TRDD, then build from the agreed design.

### VERIFIED CURRENT ARCHITECTURE (memgrep, today)
- The SQLite index (`index.rs`) has TWO recallable element kinds in the `memories` table
  (`element_type ∈ {memory, note}`):
  - **`memory` rows = one per PAGE** — surface = frontmatter `title`/`description`/`tags`; the page
    `body` is FTS-indexed (`memories_fts` over title+description+body) but only as a PAGE-granular
    secondary signal.
  - **`note` rows = one per `[^N]` LESSON** — individually indexed in the `notes` table with the
    lesson's `[ocd: lmd:]` metadata prefix (`notes_fts` over the lesson body). **Lessons are the
    ONLY first-class sub-page elements today.**
- `recall` ranks on the SYMPTOM SURFACE (frontmatter description+title+tags), precision-first; a
  body keyword hit surfaces the WHOLE page ranked by ITS frontmatter. **Body atoms (the facts
  between headings) have NO individual description/keywords/ocd/lmd/ranking — they are one opaque
  `body` blob per page.**
- Real curated page bodies today are **FREE PROSE** (`**Why:**`/`**How to apply:**` + `##`
  sections), NOT atom-delimited.

### THE TARGET (what this TRDD designs)
Make a wikimem page body a sequence of **first-class, individually-indexed ATOMS**, exactly as
`[^N]` lessons already are — each atom carrying its own keyword surface via **Obsidian Block
Properties**. Then recall can rank/return ATOMS, not just pages, and the harvest can attach
provenance to atoms meaningfully.

### THE ATOM METADATA SYNTAX = Obsidian Block Properties + AI-Maestro ARRAY extension
Base spec: https://github.com/Querulantenkind/obsidian-block-properties-plugin
- An atom is marked by a block-id + bracketed properties: **`^<block-id> [key: value, key2: value2]`**
  attached to the block (Obsidian places `^id` at the END of the block it identifies). Observed
  block-id convention (USER example): `^memory-<uid>` (e.g. `^memory-DY12UB04`) — exact uid scheme TBD.
- Base parsing rules (FOLLOW EXACTLY): a **comma SPLITS properties** (no comma in a value); the
  **FIRST colon splits** `key: value` (colons in values OK, e.g. a URL); **whitespace flexible around
  structure** (`^id[k:v]`, `^id [k: v]`, `^id [ k : v ]`); values may be `[[Note]]` links or
  `^block-ref` refs (so a correct parser BALANCES brackets and splits on TOP-LEVEL commas only);
  every prop auto-generates a CSS class `bp-{key}-{value}`.
- **AI-Maestro EXTENSION — ARRAY values (USER-specified 2026-06-23, "divided by spaces").** A property
  value is a **SPACE-separated ARRAY** of one or more values. So after the first-colon split, TRIM the
  value, then SPLIT ON WHITESPACE → the value array (a value with no internal space = a 1-element
  array). This is what gives each atom its own keyword surface. USER example:
  ```
  ^memory-DY12UB04[ type: feat-req, blocked-by: #56 #123 #27, keywords: landing-page frontend next.js webdev entry-menu, assigned-to: peter.m@mail.com susanne.sommers@box.com henry123@interw.org ]
  The issue is...
  ```
  → `type=[feat-req]`, `blocked-by=[#56,#123,#27]`, `keywords=[landing-page,frontend,next.js,webdev,
  entry-menu]`, `assigned-to=[3 emails]`. **`keywords:` is the per-atom RECALL SURFACE** — the array
  of search terms that makes an atom individually findable (resolves the "can't attach keywords to a
  single atom" gap; partly answers Q3). The full value grammar: comma → properties; first-colon →
  key/value; whitespace → array elements within a value.
- TWO metadata LEVELS — do NOT conflate: PAGE frontmatter (`---` YAML) vs per-ATOM block-properties
  (`^id [...]`). Memorized: USER-scope `wikimem-atom-block-properties.md` (+ its `[^1]` lesson).

### THE FOUR DESIGN AREAS (what the build must cover)
1. **Atom as a first-class index element.** Extend `index.rs`: parse each page body into atoms
   (delimited by their block-property markers), emit one index row per atom (`element_type: atom`,
   FK→page) with its own surface (the atom's block-prop `description`/`tags` + `ocd`/`lmd` + the
   atom text FTS). Model it on the EXISTING `notes`/lesson row machinery (the proven precedent).
2. **Block-properties parse/index/recall.** A correct Obsidian-block-properties parser (balanced
   brackets, top-level-comma split, first-colon split, whitespace-flex, `[[link]]`/`^ref` values).
   `recall` returns atoms ranked by their own surface (a page still recallable as its lead/overview).
   Decide the recall output shape (atom + its page context) and how page-vs-atom results interleave.
3. **Harvest-into-atoms (supersedes TRDD-ab232dbd's harvest mechanics).** Import each Claude buffer
   memory as an ATOM added to the APPROPRIATE topic page (a new page ONLY when no topic page exists),
   stamped with provenance block-properties `claude_mem_ref: <buffer-rel-path>` +
   `claude_mem_hash: <sha256-16>`. `memgrep find-claude-mem-ref` finds atoms by their `claude_mem_ref`
   block-property (NOT page frontmatter — the committed v1 is wrong, see below).
4. **Migration: existing free-prose pages → atoms.** A pass that segments today's free-prose page
   bodies into atoms with block-property markers (ocd/lmd carried from the page or `[^N]` dates),
   non-destructive + verified (no fact lost), one page at a time across heartbeats. RULE-0-safe.

### IN-FLIGHT CODE STATUS (what this session already touched — reconcile in the build)
- ✅ KEEP (valid, tested, survives): `scripts/lib/memory_scopes.py` `resolve_wiki_dir()` +
  `is_curated_wiki_page()` + 4 tests (the buffer/`wiki/` separation + raw-vs-curated discriminator
  are model-agnostic). Currently UNCOMMITTED in the working tree.
- ⚠ REWORK: `memgrep find-claude-mem-ref` (COMMITTED 4ebd891, installed) reads PAGE FRONTMATTER
  `claude_mem_refs: [path@hash]` — WRONG model. Must be reworked to scan per-ATOM block-property
  markers `^id [… claude_mem_ref: … claude_mem_hash: …]`. Harmless until then (new subcommand,
  nobody calls it; full memgrep suite green).
- ⚠ REWORK / SUPERSEDED: `skills/janitor-memory-harvest/SKILL.md` (UNCOMMITTED) was rewritten for
  the wrong model (frontmatter provenance, file-per-note). Redo for atoms-into-topic-pages.
- ✅ ab232dbd valid parts carry forward: buffer⇄wiki coexistence, the `memory/wiki/` namespace,
  separate-copies, the additive/never-touch-buffer invariant, the frontmatter discriminator.
  ab232dbd's HARVEST MECHANICS are superseded by area 3 here → ab232dbd is BLOCKED-BY this TRDD.

### OPEN DESIGN QUESTIONS (resolve with USER before/within build)
- Q1 **Atom segmentation of a page** — is an atom one block (paragraph/list-item/table/code-fence)
  ending in `^id [props]`, or a span of blocks up to the next marker? (The USER said an atom can be
  MULTI-paragraph + include tables/math/code — so a marker likely closes a multi-block atom; define
  the exact delimiter rule.)
- Q2 **Marker placement** — Obsidian puts `^id [props]` at the END of a block; the USER earlier said
  "before the paragraph." Confirm leading vs trailing for OUR atoms (affects parser + authoring).
- Q3 **Required atom props** — which block-prop keys are mandatory (`ocd`, `lmd`, `type`,
  `description`/keywords for the recall surface) vs optional.
- Q4 **Recall ranking** — how atom-level results and page-level (lead/overview) results interleave;
  does a page still get a row, or only its atoms + a synthetic lead?
- Q5 **Migration trigger/cadence** — autonomous heartbeat pass vs explicit; ordering vs the harvest.
- Q6 **Backward compat** — `[^N]` lessons already ARE atoms-with-metadata; unify them with the new
  atom model or keep both element kinds?

### NEXT ACTION
1. USER reviews this design + answers Q1–Q6 (or says "your call" per question).
2. Split into build NPTs (likely: (a) block-properties parser + tests; (b) indexer atom rows;
   (c) recall atom output; (d) harvest-into-atoms rework + find-claude-mem-ref rework;
   (e) prose→atom migration pass). Each its own TRDD child, TDD, sequential commits.
3. ab232dbd resumes on top once (a)–(d) land.

## Notes and lessons learned
[^1]: [ocd:2026-06-23 lmd:2026-06-23] The harvest was being built against a memory-atom model that
  memgrep does not actually implement (page+lesson granularity only, no atom indexing). Root cause:
  implemented BEFORE recalling/verifying the memory model, and the load-bearing convention (Obsidian
  block-properties for per-atom metadata) was never memorized so recall returned nothing. Lesson:
  RECALL + VERIFY the data model against the code BEFORE building on it; an absent load-bearing
  convention IS the bug — memorize it first (done: `wikimem-atom-block-properties.md`), then design.
