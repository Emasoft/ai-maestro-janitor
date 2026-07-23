---
trdd-id: VJCMZ2OP
title: memgrep migrate — move an atom and all its baggage between wikimem pages
column: backburner
created: 2026-07-23T06:35:11+0200
updated: 2026-07-23T06:35:11+0200
current-owner: claude-ai-maestro-janitor
task-type: feature
severity: high
relevant-rules: [1]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-23

**NOT STARTED.** New verb requested by the USER this session. Does NOT exist — the write
surface is `add-atom / new-page / add-lesson` only (`scripts/memgrep/src/main.rs:388-391`,
re-verified 2026-07-23). Building it is the ONLY safe way to honour the atom-travels-with-its-
baggage rule: a hand-move drops lessons and collides footnote numbers.

**NEXT ACTION:** add `Some("migrate") => memory::cmd_migrate_cli(&raw[2..])` to the dispatch
match and implement `cmd_migrate_cli` in `scripts/memgrep/src/memory.rs` per the contract
below. Wire it through `memory_txn` so both pages are edited in ONE crash-safe transaction.

## The command (USER, verbatim intent)

```
memgrep migrate <atom-id> --from <wikimem page path> --to <wikimem page path>
```

Move the atom AND all its baggage (notes, lessons learned, See-also / link references) from
the source page to the destination page.

## The contract (every clause is load-bearing)

1. **Move the atom + its baggage.** The atom block, its `[^N]` lessons, and the refs those
   lessons/atom use travel together.
2. **KEEP shared refs on the source.** A `[^N]` reference still used by ANOTHER atom on the
   source page is NOT moved — it stays where the other atom can still resolve it. Only refs
   used solely by the migrating atom leave.
3. **RENUMBER refs unique in the destination.** The moved refs are re-anchored to `[^N]`
   numbers that are free on the destination page (its footnote ids are page-local and must
   stay unique), rewriting both the definitions and the inline references consistently.
4. **VALIDATE + FIX BOTH pages FIRST.** Before moving anything, run `validate` + `lint` on
   BOTH the source and destination and repair any formatting error. CRITICAL: migrating
   across a malformed page corrupts BOTH pages — a mis-numbered or unquoted-desc source makes
   the ref-renumbering arithmetic wrong, and a broken destination silently swallows the moved
   block. This pre-flight is not optional.
5. **One atomic transaction.** Source-edit + destination-edit commit together through
   `memory_txn`; a failure mid-move rolls both back. The `verify_*` oracle
   (`memory_edit_verify.py`) proves no lesson/fact was lost across the two pages.
6. **Bidirectional links.** Any `[[wikilink]]` to/from the atom is repointed per the LINK LAW
   so the move leaves no dangling ref (`no_dangling_refs`).

## Why a verb, not a hand-move

Points 2 + 3 are the trap: a human moving an atom either drags a shared ref away (breaking the
other atom) or reuses a footnote number that already exists on the destination (two `[^1]:`
blocks — the exact defect TRDD-SYAPZXQK §1 records from a real merge). Point 4 is the second
trap: the arithmetic depends on both pages being well-formed. Only a tool can do all of this
transactionally.

## Verification

- Migrate an atom whose lesson shares a ref with a sibling atom: the sibling still resolves;
  the shared ref stayed on the source; the atom's own refs are renumbered unique on the dest.
- Migrate onto a page that already uses the atom's original footnote numbers: no collision;
  both pages lint clean afterward.
- Migrate with a deliberately malformed source: the pre-flight validate/fix runs first (or the
  migrate refuses with a clear message) — BOTH pages remain well-formed, never corrupted.
- A mid-transaction abort leaves both pages exactly as before.
- `cargo test` (memgrep) covering the ref-partition + renumber logic; `pytest` verify_* green.

## Notes and lessons learned
