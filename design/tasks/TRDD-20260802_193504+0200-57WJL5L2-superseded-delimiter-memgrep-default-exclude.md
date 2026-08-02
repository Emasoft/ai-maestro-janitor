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
