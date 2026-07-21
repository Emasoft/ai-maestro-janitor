---
trdd-id: R02HTRUD
title: memgrep mechanical wikimem write verbs — add-atom add-lesson new-page, correct syntax by construction
column: todo
created: 2026-07-21T12:12:44+0200
updated: 2026-07-21T12:12:44+0200
current-owner: claude-ai-maestro-janitor
task-type: feature
scope: project
eht: [6RO0L3M0, 5FNZ7ZKO]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-21

**Owner directive (2026-07-21, verbatim intent):** never hand-write a wikimem `.md` again — the
agent passes only `(body, keywords)`; the tool (memgrep) synthesizes everything else (a
corpus-unique id, `ocd`/`lmd`, the canonical `^id [props]` block-prop formatting, the canonical
lesson form) so an atom is **written right by construction**. Every mechanically-enforceable rule
lives in the tool; only judgment stays in the skills (that split is [[TRDD-6RO0L3M0]]).

**NEXT ACTION:** in `scripts/memgrep/src/`, add the `add-atom` verb first (dispatch arm at
`main.rs:~386`; `cmd_add_atom_cli` + args struct in `memory.rs`). Build the id GENERATOR
(wrapping `atom_id_hits` memory.rs:1726 — live-walk when the index is stale, collision-retry over
BOTH atoms and lessons) and the marker EMITTER (inverse of `first_block_property_marker`
memory.rs:1339 / `parse_block_props` memory.rs:1314). Reuse the atomic temp+rename infra
(`memory.rs:1150`, `index.rs:218`) and `index::reindex` (index.rs:1071). NO new crate — seed the
id from `SystemTime` nanos (no `rand`/`uuid` in Cargo.toml today).

**LOAD-BEARING FACTS / GOTCHAS:**
- memgrep is read-only today (verbs: index/reindex/validate/recall/find/find-claude-mem-ref/
  overview). It HAS: atomic-write infra, corpus-unique-id *detection* (`atom_id_hits`), a content
  `lint` (`cmd_lint_cli` memory.rs:1948). It has NO id *generator* and NO atom *writer*.
- Canonical shape is defined SOLELY by the parser — the emitter must match it byte-for-byte:
  ASCII `^`, id charset `[A-Za-z0-9_-]`, ASCII `[` … `]`, top-level-comma-split props, `keywords`
  is the recall surface. `⟦⟧` (recall's DISPLAY escaping) is invisible to the parser — never emit it.
- The hardest sub-problems (Explore agent, 2026-07-21): (a) corpus-unique id-gen race-safe across
  atoms+lessons, correct with a stale/absent index; (b) in-place edit/delete of ONE atom without
  reflowing the page — `resolve_atoms_from_text` (memory.rs:1507) is line-based and LOSSY, so it
  can't round-trip bytes; a NEW span-locator is needed (marker line → body extent = next marker /
  next `#` heading / EOF); (c) insertion-point choice; migrate = delete-from-A + add-to-B as one op
  with rollback. `add-atom` (pure append) avoids (b); defer (b) to the edit/supersede verbs.

**SUPERSEDED — do NOT carry forward:** an earlier idea to reuse recall's display form `⟦…⟧` — WRONG,
it is invisible to memgrep's byte scan for `[` (0x5B).

## Problem

Family A of the wikimem write path (`janitor-memory-write`, `-update`, `-bootstrap`, `harvest`-create)
hand-authors `.md` via the Write/Edit tools — NO transaction, NO verify gate, NO syntax check. This
is why the three skills' three different lesson schemas produced corpus drift (153 lean lessons). A
tool that emits only the canonical form makes malformed atoms impossible.

## Approach

New memgrep write subcommands, each: pass `(body via stdin, keywords, target)` → tool synthesizes
id + ocd/lmd + canonical formatting → atomic write → reindex; REFUSE to emit anything malformed.

- `add-atom --page <path> --keywords "a,b,c" [--desc "…"] [--type …]` — append a canonical
  `^ATOM-XXXX-XXXX [desc:"…", keywords: a b c, ocd:…, lmd:…]` + body.
- `add-lesson --page <path> --atom <id> --keywords "…" [--desc "…"]` — the ONE canonical `[^N]`
  lesson form, wired to its atom's inline `[^N]` ref (kills the 3-schema drift at the source).
- `new-page --path … --tier hub|aspect|component --name … --description … --type … [--globs …]
  [--functionality …]` — scaffold complete valid frontmatter + the mandatory `## Notes and lessons
  learned` section.

The canonical form this emits is ratified by [[TRDD-5FNZ7ZKO]] (schema reconciliation); the pre-write
syntax gate + audit is [[TRDD-VPTQ4067]]. Risky EDIT/SUPERSEDE/MIGRATE ops stay in the Python
`memory_txn`+`memory_edit_verify` substrate (no id-gen/atomic-write/verifier duplication in Rust).

## Derived tasks (DERIVED, depth-1)

- Id-gen must be race-safe (no cross-process corpus lock exists today; DB busy_timeout guards only
  SQLite) — collision-retry loop + accept the small residual race, documented.
- A span-locator (for the later edit verbs) that finds a marker's byte extent without reflowing.
- Tests: id uniqueness across corpus incl. stale/absent index; canonical syntax emitted; atomic
  write; reindex sync; round-trip `add-atom` → `recall` finds it by keyword.

## Verification

`cargo test` in `scripts/memgrep`; a shell round-trip (add-atom to a temp page → `wikimem_syntax_lint`
+ `memgrep lint` both clean → `recall` finds it). Full `uv run pytest` + `ruff check` green for any
Python touched. Commit, do not push, unless asked.

## Notes and lessons learned
