---
trdd-id: 3b9b2040-42b1-4217-8268-d787b389fd05
title: Wikimem atoms as first-class index elements — block-properties parse/index/recall, harvest-into-atoms, prose→atom migration
column: dev
created: 2026-06-23T13:26:34+0200
updated: 2026-06-23T15:57:49+0200
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

### 🔴 REFINED MODEL — USER directives 2026-06-23 (SUPERSEDES the trailing/2-element build below)
The atom engine (a–f below) was built with a model the USER then corrected in a rapid series of
directives. The CORRECT model — memorized at USER scope in [[wikimem-atom-block-properties]] +
[[wikimem-single-memory-agent]] (recall them) — is:

1. **EVERY element carries a LEADING metadata block.** A wikimem page is `frontmatter → TOC →
   ## chapter/### subsection headings (each holding memory ATOMS) → # Notes → # Lessons Learned →
   # See also`. The FOUR element kinds — **atom, note, lesson-learned, see-also** — EACH begin with
   a block-properties metadata block `^memory-<id> [keywords: …, …]` on its OWN line, with the
   element's content BELOW it (LEADING, not trailing — the USER's examples always put the marker on
   top). The metadata block OPENS the element; its content runs until the next block / heading.
2. **memgrep greps the ELEMENTS, not the page.** The metadata blocks are what memgrep indexes/ranks
   (by each element's `keywords:`). It reports the containing page only as CONTEXT. The agent is
   DISCOURAGED from reading the whole page (read it only when wholly ignorant of a topic). Grepping a
   topic returns ALL its atoms.
3. **A lesson-learned = a PREVIOUS VERSION of an atom.** Every UPDATE demotes the old atom into a
   lesson-learned: metadata = change-date + the atom's ORIGINAL metadata; content = the old version +
   a concise WHY it was superseded. Demote, never delete.
4. **notes / lessons / see-also are markdown FOOTNOTES `[^N]`** (USER-confirmed "yes", 2026-06-23).
   All three use the SAME footnote syntax: a `[^N]` ref in the atom body → a `[^N]: …` definition in a
   bottom `# Notes` / `# Lessons Learned` / `# See also` section. Notes are referenced mid-text;
   lessons/see-also are clustered at the END of the atom text (inline allowed). Definitions are POOLED
   at the bottom because **one footnote can be SHARED by multiple atoms**. **Returning an atom =**
   the atom + its `[^N]`-referenced notes/lessons/see-also, aggregated (NEVER the bare atom). **MOVE
   RULE:** moving an atom to another page ref-counts its footnotes — do NOT delete a `[^N]` definition
   from the source if another atom there still references it (shared-footnote GC; merge/split/harvest).
5. **ONE memory agent for ALL chores** (`janitor-memory-subconscious-agent`) — never one-agent-per-
   chore; the `janitor-memory-*` under `skills/` are PROCEDURES it loads, not agents. Invoked by main
   Claude OR as an async background task, one chore/launch, **loading ONLY that chore's skill
   dynamically** to save tokens.

**PHASE g — REFINE the engine to the confirmed model (the `[^N]` footnote foundation is RIGHT; this refines it, not rips it):**
- **g1 ✅ DONE (commit a4e5d74)** — flipped the ATOM marker to LEADING: `first_block_property_marker`
  returns `(start, end, id, props)`; `resolve_atoms_from_text` rewritten to an OPEN-atom accumulator
  (marker opens an atom; content below it until the next marker / a `#`-heading / EOF is its body;
  pre-first-marker + post-heading content belongs to no atom; fence + frontmatter handling preserved;
  new `make_atom` helper). Flipped the memory.rs unit tests + cli.rs ATOM_CORPUS to leading. 125 green.
- **g2 ✅ DONE (commit 3da1240)** — `render_atom_record` groups an atom's `[^N]` footnotes by section:
  `footnote_sections(text)` classifies each `[^N]` def by its nearest preceding heading
  (`classify_heading` priority see-also > lesson > notes); `enum SectionKind {Notes,Lessons,SeeAlso}`;
  render emits non-empty labeled groups `notes:` / `lessons learned:` / `see also:`. Removed
  `atom_wikilinks` + the `[[link]]`-as-see-also path (body keeps `[[links]]` inline as page-level text;
  atom see-also is now `# See also` footnotes). New grouping test. 126 green, clippy clean.
- **g3 ☐ TODO — shared-footnote ref-counting on atom MOVES** (Python verify layer:
  `scripts/lib/memory_edit_verify.py` + `memory_txn`). When split/merge/harvest MOVES an atom to
  another page, move its `[^N]` defs too, but do NOT delete a note/lesson/see-also def from the source
  page while ANOTHER atom there still references it (ref-counting GC). Add a `verify_*` check.
- **g4 ☐ TODO — recall presentation**: atoms already interleave with pages by score (DONE in phase c);
  remaining is the UX/doc that recall surfaces ELEMENTS with the page as context only + discourage
  full-page reads (largely a `janitor-memory-recall` skill + `memgrep SKILL.md` wording task).
- **g5 ☐ TODO — atomize skill**: `skills/janitor-memory-atomize/SKILL.md` must emit LEADING atom blocks
  + the `# Notes`/`# Lessons Learned`/`# See also` footnote-pool layout (currently describes trailing).
- **g6 ☐ TODO — docs/skills**: `wikimem-model.md`, write/recall skills, `scripts/memgrep/SKILL.md` to
  the leading + footnote model. USER-scope memory already updated ([[wikimem-atom-block-properties]] [^4]).
- NEXT ACTION: g3 (the move-rule verify) is the next CODE piece; g4–g6 are doc/skill alignment. The
  engine (g1+g2) is shippable interim. Reinstall the binary (`cargo install --path scripts/memgrep`)
  so the live system runs the leading parser (moot today — live corpus is free-prose, no markers yet).

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
- ✅ REWORKED (Phase a): `memgrep find-claude-mem-ref` no longer reads PAGE FRONTMATTER
  `claude_mem_refs:` — it now LIVE-scans per-ATOM block-property markers `^id [… claude_mem_ref: …
  claude_mem_hash: …]` via `resolve_atoms` and prints `path#atom-id\thash`. Phase (d) will swap the
  live scan for the indexed `atoms.claude_mem_ref` column once Phase (b) lands the index table.
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

### DESIGN DECISIONS — RESOLVED on USER "complete everything" delegation (2026-06-23)
- **Q1/Q2 — atom = content + a TRAILING `^memory-<uid> [props]` marker (Obsidian).** The marker
  CLOSES the atom; the atom body = the contiguous content preceding it, back to the prior marker /
  `##` heading. A multi-paragraph/table/code atom is one span ended by one marker.
- **Q3 — `keywords:` is the only REQUIRED prop** (the recall surface). `ocd`/`lmd`/`type` optional
  (fall back to the page's); `claude_mem_ref`/`claude_mem_hash` only on harvested atoms.
- **Q4 — recall returns ATOMS (ranked by keyword surface) + pages + lessons, interleaved by score.**
  An atom result prints `path#atom-id — <keywords>`; the page stays recallable as its lead.
- **Q5 — migration = a new autonomous `[janitor-memory-atomize]` pass** (one page/run, txn-guarded,
  verify no fact lost) AND a one-time corpus atomization (agents, batched).
- **Q6 — KEEP `notes` (lessons) + `atoms` as SEPARATE index tables** (don't merge a proven path;
  unify later). Both are first-class sub-page recall elements.

### NEXT ACTION — BUILD (USER authorized full implementation + migration 2026-06-23)
Build order (TDD, sequential commits): **(a)** ✅ DONE — block-properties parser w/ array-values
(`parse_block_props`, `first_block_property_marker`) + `resolve_atoms`/`resolve_atoms_from_text` +
`struct Atom` in `memory.rs`; `find-claude-mem-ref` reworked off page-frontmatter onto a LIVE atom-scan
of `claude_mem_ref` block-props (output `path#atom-id\thash`); 4 new tests, full suite 86 green.
**(b)** ✅ DONE — `atoms(memory_id FK, atom_id, keywords, ocd, lmd, atom_type, claude_mem_ref,
claude_mem_hash, body)` + `atoms_fts(keywords, body)` in `index.rs`; `insert_file` atoms-loop (after
the lessons loop) via `resolve_atoms_public`; `delete_rows_for_path` clears atoms + FTS; `SCHEMA_VERSION
= 2` migration clears the `files` ledger on a version bump so the next reindex re-parses an UNCHANGED
corpus to fill atoms (verified by `schema_migration_reparses_unchanged_corpus_to_fill_atoms`); 3 new
index tests, full suite 119 green (33 unit + 86 integration).
**(c)** ✅ DONE — recall now surfaces ATOMS interleaved with pages by score. `CandidateMeta`/`RecallScored`/
`RecallRanked` gained a trailing `atom_id` discriminator threaded through `score_candidate`; `gather_from_walk`
(via `resolve_atoms`) + `gather_from_index` (via new `index::recall_atom_candidates`, page-date COALESCE
fallback) both emit atom rows ranked by the keyword surface; `finalize_recall` prints an atom as
`path#atom-id — <keywords>` with NO lesson append (a page still appends its `[^N]` lessons). `is_fresh`
gained a `user_version < SCHEMA_VERSION` gate (a pre-v2 index → walk, which DOES surface atoms) +
`recall_atom_candidates` tolerates a missing atoms table (explicit `--use-index` on an un-migrated DB).
3 integration tests (atom-by-keyword, walk==index parity, find-cmref CLI); full suite 122 green.
**(d)** ✅ DONE — `find-claude-mem-ref` uses the FRESH index (`index::claude_mem_ref_atoms`, covered by
`idx_atoms_cmref`) when one exists — the harvest calls it once per buffer memory, so an O(matching-atoms)
SQL lookup beats re-parsing every wiki page each call — and live-scans otherwise; both apply the
exact/basename match and emit byte-identical sorted output (proven by `find_claude_mem_ref_index_matches_live_scan`).
clippy `-D warnings` clean (collapsed let-chain + dropped redundant `.trim()`); memgrep installed to
`~/.cargo/bin`; full suite 123 green. **Rust engine (a–d) COMPLETE.**
**(e)** ✅ DONE — docs/skills teach atom authoring + atom recall: `scripts/memgrep/SKILL.md` ("Atoms —
per-fact recall"), `rules/markdown-memory-recall.md`, `skills/janitor-memory-write/SKILL.md` +
`references/wikimem-model.md` ("Atoms — first-class body elements"), `skills/janitor-memory-recall/SKILL.md`
("Results now include body ATOMS"). NOTE harvest-into-atoms is ab232dbd's separate large scope (buffer
coexistence) — its buffer is DORMANT (MEMORY.md is a stub, 0 raw notes), so this TRDD ships the atom
ENGINE + atom RECALL + the atomize MIGRATION; ab232dbd stays blocked-by this and owns the harvest rewrite.
**(f)** ✅ DONE — `[janitor-memory-atomize]` migration pass: `verify_atomize` gate (memory_edit_verify) +
`--op atomize` (memory_txn_cli, repair-class 1-write-0-delete) + `atomize_per_day` cadence
(memory_settings) + the `[janitor-memory-atomize]` marker (memory-maintenance scheduler) + the
janitor-arm cron clause + the subconscious-agent roster + the new `skills/janitor-memory-atomize/SKILL.md`
executor. 5 verify tests + an e2e txn smoke (begin→stage→commit --op atomize→reindex→recall the atom) green.

### ⚠ USER CORRECTION (2026-06-23) — notes/lessons/see-also are PER-ATOM, not per-PAGE
I initially built recall so a returned atom carried the PAGE's `[^N]` lessons. **The USER corrected
this: every ATOM owns its OWN notes/lessons-learned/also-see.** A lesson = a PREVIOUS VERSION of THAT
atom (demoted on update, with the change-date + the original metadata + a concise WHY it was
superseded). On the page the structure stays Wikipedia-shaped (the lead atom on top, the `[^N]`
footnote pool + `also see` links at the bottom, tied by INLINE references), but **on recall memgrep
returns each atom AGGREGATED into its full self-contained record**: `^memory-<id> [props]` locator →
the atom's content (multi-paragraph/table/code/math/links) → its `[notes]` → its `[lessons learned]`
→ its `[also see: [[…]]]`. Fixed in `render_atom_record` (memory.rs): an atom's notes = the `[^N]`
footnotes ITS body references (regex `atom_referenced_labels`), its "also see" = the `[[wikilinks]]`
in ITS body (`atom_wikilinks`). Also FIXED `resolve_atoms_from_text` (was absorbing the leading
`---`frontmatter`---` + the H1 into the first atom's body — now skips frontmatter and treats ANY
`#`-heading as a boundary; locked by `resolve_atoms_excludes_frontmatter_and_headings_from_body`).
Full memgrep suite 125 green; all 6 atom docs corrected to the per-atom aggregation model.

### STILL OPEN (the only remaining work on THIS TRDD)
- The atomize pass is WIRED (cadence + marker + skill + verify) so the heartbeat atomizes the corpus
  incrementally, one page/run — the design's chosen path over a risky big-bang of ~30 live pages.
- PUBLISH: the USER authorized push+publish; this TRDD's atom engine is shippable via `publish.py`.
  ab232dbd's harvest-coexistence rewrite is SEPARATE and stays deferred (its buffer is dormant).

## Implementation blueprint — mirror the lesson-indexing precedent (VERIFIED 2026-06-23)

The atom build is NOT greenfield: `[^N]` lessons are ALREADY first-class index elements, and atoms
mirror that machinery exactly. The ROW MODEL below is INVARIANT to the Q1–Q6 answers (those shape
the PARSER + the ranking, not the row model) — so it can be locked in now.

**How a lesson becomes a first-class index row today** (`scripts/memgrep/src/index.rs::insert_file`
+ `memory.rs::resolve_notes`, verified):
1. The PAGE → one `memories` row (`element_type='memory'`, `body`=full text), FTS-shadowed in
   `memories_fts(title, description, body)`.
2. Each lesson → `resolve_notes_public(path)` yields `ResolvedNote{num, ocd, lmd, text, urls}`; each
   becomes one `notes(memory_id FK, label, ocd, lmd, body, urls)` row + a `notes_fts(body)` shadow —
   so a lesson carries its OWN ocd/lmd and its OWN FTS surface; it is individually recallable.
3. `delete_rows_for_path` clears a page's `memories` + `notes` + both FTS shadows before re-insert.

**The atom build mirrors this exactly:**
- ADD `resolve_atoms_public(path)` (parallel to `resolve_notes`) — parse the body into atoms delimited
  by their `^id [block-props]` markers; yield `Atom{ id, keywords[], ocd, lmd, atom_type,
  claude_mem_ref, claude_mem_hash, body }`. (Block-props parser already specified: comma→props,
  first-colon→k/v, whitespace→array. Q1/Q2 fix the body-span + marker-placement rule.)
- ADD an `atoms(memory_id FK, atom_id, keywords, ocd, lmd, atom_type, claude_mem_ref, claude_mem_hash,
  body)` table + `atoms_fts(keywords, body)` — exactly parallel to `notes`/`notes_fts`. The atom's
  RECALL SURFACE is its `keywords:` array (mirroring how a page's surface is its `description`).
- EXTEND `insert_file` with an atoms loop (after the lessons loop) + `delete_rows_for_path` to clear
  atoms + `atoms_fts`.
- `recall` gains atom candidates ranked by the keyword surface (Q4 decides atom-vs-page/lead
  interleaving). `find-claude-mem-ref` then reads the indexed `atoms.claude_mem_ref` column instead of
  live-scanning (replacing the committed v1, 4ebd891).
- A schema bump + a `--full` reindex migrates existing indexes; pages with no atom markers yield zero
  atom rows until the prose→atom migration (area 4) runs.

**Q-dependence:** the ROW MODEL is invariant. Q1/Q2 shape `resolve_atoms`'s parser; Q3 shapes which
`atoms` columns are NOT NULL; Q4 shapes recall interleaving; **Q6 (unify `[^N]` lessons with atoms)
could MERGE the `notes` + `atoms` tables — decide BEFORE building the schema** (a lesson IS already an
atom-with-metadata, so unifying is attractive but touches the proven lesson path).

## Notes and lessons learned
[^1]: [ocd:2026-06-23 lmd:2026-06-23] The harvest was being built against a memory-atom model that
  memgrep does not actually implement (page+lesson granularity only, no atom indexing). Root cause:
  implemented BEFORE recalling/verifying the memory model, and the load-bearing convention (Obsidian
  block-properties for per-atom metadata) was never memorized so recall returned nothing. Lesson:
  RECALL + VERIFY the data model against the code BEFORE building on it; an absent load-bearing
  convention IS the bug — memorize it first (done: `wikimem-atom-block-properties.md`), then design.
