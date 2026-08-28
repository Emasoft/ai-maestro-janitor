---
trdd-id: YMDE95LT
title: Duty 18 — every atom carries a backlink to the TRDD that produced it
column: complete
created: 2026-08-28T07:52:50+0200
updated: 2026-08-28T08:56:21+0200
current-owner: janitor-session
task-type: feature
project-id: ai-maestro-janitor
parent-trdd: 87RKBYJ8
npt: []
eht: []
min-approval-requirement: none
---

# Duty 18 — TRDD backlinks per atom

Split out of **TRDD-87RKBYJ8** per its own rule.

## What is missing

An atom records WHAT is true. It does not record WHICH decision produced it. So the provenance
chain that `commit-discipline.md` describes — memory → TRDD → `implementation-commits:` →
`git show <sha>` — dead-ends at the first hop for any atom written without one.

## Why it matters more than tidiness

The maintainer chores demote an obsolete fact to a dated lesson **without inventing the reason** by
sourcing it from that chain. An atom with no TRDD backlink cannot be demoted safely: the chore
either invents a rationale or leaves a known-stale fact standing. Both are worse than the
bookkeeping this duty costs.

## Design constraint

The backlink must be OPTIONAL on read and CHEAP on write — a corpus of ~276 existing atoms has
none, and a validator that hard-fails on their absence would block every write until a mass
migration ran. Add it as an additive prop, warn (never error) on absence, and let it accrete.

## Acceptance

- [x] Atoms may carry a `trdd:` prop; write verbs accept and preserve it
- [x] Absence WARNs, never errors — the existing corpus keeps working untouched
- [x] `memgrep` can answer "which atoms came from TRDD-X"
- [x] `uv run pytest -q`, ruff, mypy

## What shipped (2026-08-28)

Spec: **WM-CLI-17** (the prop + its optionality) and **WM-CLI-18** (`find-trdd`).

- `Atom.trdd` parsed from a `trdd:` block-prop; `build_atom_marker` emits it between `type` and
  the dates — with the identity fields, not the lifecycle ones.
- `new-mem-atom --trdd` and `update-mem-atom --trdd` (the latter is the BACK-FILL path for the
  ~276 atoms that predate the field). Both accept `TRDD-XXXXXXXX` / `#XXXXXXXX` / bare 8 chars in
  any case and canonicalise; an unparseable citation is REFUSED (exit 1) rather than stored.
- `update-mem-atom` re-emits an existing backlink in its canonical position instead of letting it
  fall through to the unknown-prop tail; `split-mem-atom` copies it onto the new half.
- `find-trdd <TRDD-ID> [PATHS]` — the reverse hop, a live walk.

Verified on the installed binary via the bare command name, not `cargo run`: stamp → warn →
query → back-fill → refuse, then `validate` + `lint` clean. Rust 246 unit + 146 integration;
`pytest` 15894 passed / 0 failed; ruff + mypy clean over 494 files.

**Two decisions worth keeping:**

1. **No `atoms.trdd` index column.** `claude_mem_ref` has one because the harvest queries it once
   per buffer note in a loop; this query is occasional. Buying it speed would cost a new schema
   version whose migration CLEARS the file ledger — forcing a full re-parse of every corpus on
   the machine, a large certain cost against an unmeasured saving. The live walk is the same code
   path `claude_mem_ref_hits` already falls back to, so it is proven, not new.
2. **`find-trdd` validates its QUERY.** A typo'd query would otherwise return a confident empty
   list, which reads as "this decision produced no memory" — the one wrong answer a provenance
   tool must not give silently.

## Notes and lessons learned
