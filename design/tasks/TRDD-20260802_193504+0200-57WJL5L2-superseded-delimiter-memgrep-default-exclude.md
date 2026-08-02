---
trdd-id: 57WJL5L2
title: Superseded-atoms-below-a-delimiter convention + memgrep default-exclude
column: todo
created: 2026-08-02T19:35:04+0200
updated: 2026-08-02T19:35:04+0200
current-owner: janitor-session
task-type: feature
severity: medium
scope: project
release-via: publish
created-by: 87RKBYJ8
npt: []
eht: []
implementation-commits: []
---

# Superseded atoms below a delimiter — memgrep excludes them by default

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative)

**Not started.** Child 1 of 4 split out of TRDD-87RKBYJ8 (duties 7-8 — the HIGHEST-value gap
per both the card's own NEXT ACTION and the independent 2026-08-02 re-audit: every `recall`
today mixes obsolete facts with current ones).

**DESIGN REFINEMENT (2026-08-02 19:55, recorded before implementation):** key the
default-EXCLUDE on the atom's own **`status:` prop** (atoms already carry
`status:valid` / `status:superseded` in their marker props — authoritative, position-independent
metadata memgrep already parses), NOT on body position relative to a delimiter. A positional
mechanism is fragile (one mis-placed atom silently flips its visibility) and demands the
reorder pass for CORRECTNESS; status-keyed filtering is correct immediately, and the
delimiter + reorder pass become the READABILITY layer (humans see current facts first), with
the lint check (`superseded atom above the delimiter` = WARN) tying the two together. The
duty's stated GOAL is "memgrep shows only up-to-date atoms by default, excluded unless the
filter params request them" — the delimiter was the suggested mechanism, not the goal.
⚠ Implementation gotchas found while sizing: BOTH the index-backed and the walk recall paths
must filter (`memory.rs` `recall_*` + `find_gather_walk`, `index.rs` `recall_*_candidates`);
the SECOND HOP (`recall <ATOM-ID>`) must STILL return a superseded atom when addressed by id
(an explicit address is an explicit request); and `scripts/wikimem_bench.py`'s regression gate
(accuracy may never drop) must be re-run — if any benchmark-expected atom is superseded, the
bench expectations need reconciling, not the filter weakening.

## The ask (from the parent's duty rows 7-8, MISSING as of the 2026-08-02 audit)

Page body STRUCTURE: up-to-date atoms in the UPPER part, superseded/lessons-learned atoms in
the LOWER part, separated by a **clear delimiter memgrep can key on** — and `memgrep`
(recall/find) EXCLUDES everything below it by default, unless the filter params explicitly
request superseded content.

## Smallest shippable step (audit recommendation, verified against the tree)

1. Define the delimiter in the wiki model (e.g. a `## Superseded` heading — pick ONE canonical
   spelling, document it in `memory-system` / the wikimem model page).
2. `memgrep` (Rust, `scripts/memgrep/`): recall/find skip content below the delimiter unless a
   new `--include-superseded` flag is passed. Lint gains a check that superseded-status atoms
   sit BELOW it (WARN above).
3. A reorder pass (subconscious-agent chore procedure) that moves `status: superseded` atoms
   below the delimiter — verified lossless via the `verify_*` oracle (atoms MOVE, never
   deleted; lessons travel).

Zero hits today for any of this — verified 2026-08-02 (grep `include-superseded`,
`## Superseded`, `exclude…superseded` across `scripts/memgrep/src/*.rs` + all skills).

## Verification

- `memgrep recall` on a page with a superseded atom below the delimiter does NOT return it;
  `--include-superseded` does.
- `memgrep lint` warns on a superseded atom ABOVE the delimiter.
- The reorder pass round-trips a fixture page with zero knowledge loss (oracle green).

## Notes and lessons learned
