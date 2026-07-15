---
trdd-id: 0NGYP3IG
title: memgrep atom-id resolution — id to page-path for wiki navigation, and id to atom content
column: backburner
created: 2026-07-15T20:02:05+0200
updated: 2026-07-15T20:02:05+0200
current-owner: janitor-session
task-type: feature
scope: project
severity: major
labels: [wikimem, memgrep, memory-recall, navigation]
parent-trdd: AP2X9A0H
relevant-rules: []
---

# memgrep atom-id resolution — id→page-path (wiki navigation) and id→atom content

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-15

**The ask (USER, 2026-07-15):** memgrep's MAIN function is to resolve an **atom id** two ways, using
the always-updated background index:

1. **id → PAGE PATH.** Given an atom id, return the PATH to the wikimem page that CONTAINS that atom.
   The **page path + the atom id together are sufficient to navigate the wiki like a browser navigates
   Wikipedia** — you land on the page and jump to the atom. This is the navigation primitive.
2. **id → ATOM CONTENT.** When only the atom's content is needed, the **atom id alone must be enough**
   for memgrep to find and RETURN just that atom (no page load required).

The **background-updated index** (`.memgrep` SQLite sidecar) gives memgrep everything it needs to
resolve an id to either its page path or its content, fast.

**WHY the index is the ONLY reliable source of the atom→page mapping (USER, 2026-07-15):** atoms are
**MOBILE** — the subconscious agent MOVES an atom from one wikimem page to another when it
splits / merges / extends / reduces / relocates-to-the-right-topic a page (TRDD-87RKBYJ8). So the
page that contains a given atom **changes over time**; the page path must NEVER be baked into the atom
or hardcoded anywhere — it is resolved through the always-updated index, which alone knows where the
atom lives at THIS moment. This is the load-bearing reason id→page-path must be an index lookup, not a
stored back-reference.

**THEREFORE atom ids must be GLOBALLY-UNIQUE 8-char UUIDs (corpus-wide, latin letters + numbers).**
Because an atom keeps its id when it moves between pages, the id must be unique across the WHOLE
corpus — not merely within its current page. Format: 8 alphanumeric chars `[A-Z0-9]` (the existing
`ATOM-XXXX-XXXX` shape carries exactly 8 payload chars). The id generator MUST check the index for a
collision across ALL pages/scopes before assigning a new id (an id reused on two atoms breaks both
resolution modes — id→page becomes ambiguous, id→content returns the wrong atom). Corpus-wide id
uniqueness is a hard invariant memgrep's index can and must enforce/verify.

**Existing state (RECALLED — verify before implementing):** per `wikimem-atom-block-properties-
harvest-and-status.md` ⟦2⟧ and TRDD-3b9b2040, the atom engine is ALREADY built: block-properties
parser + `resolve_atoms`, the `atoms` / `atoms_fts` index tables (schema-v2), atom-level recall, and
`find-claude-mem-ref` on the indexed provenance column (125 memgrep tests green). So id→content likely
already exists in some form. **This TRDD is: confirm both resolution modes exist as first-class,
ergonomic commands, and add whichever is missing** — especially the id→page-path navigation output
(the "browse the wiki" primitive) and a clean id→atom-only fetch.

## NEXT ACTION
1. Audit `scripts/memgrep` (Rust): does it expose (a) `atom id → owning page path`, and (b) `atom id
   → atom content only`, both index-backed? Check `resolve_atoms` + the `atoms` table columns (does a
   row carry its page path?).
2. Add/confirm two ergonomic commands (names TBD): one prints the OWNING PAGE PATH for an atom id
   (navigation — page path + id is the address), one prints just the ATOM CONTENT for an atom id.
3. Ensure the background index carries page-path per atom so both are O(1) lookups; keep it current
   (the existing reindex/watch path).
4. Tests (Rust): id→page-path returns the correct owning page; id→content returns only that atom;
   both work off the index without scanning files.
5. Publish (memgrep binary lives in the plugin → release + cache update to deploy, per
   `macos-keychain.md [^2]` / TRDD-EQJPPZ2L: repo ≠ deployed).

## Verification
- `memgrep <id→page-path cmd> ATOM-xxxx-xxxx` → the path of the page that contains it (navigation).
- `memgrep <id→content cmd> ATOM-xxxx-xxxx` → just that atom's content (no page load).
- Both resolve purely from the background index; `cargo test` green.

## Notes and lessons learned
