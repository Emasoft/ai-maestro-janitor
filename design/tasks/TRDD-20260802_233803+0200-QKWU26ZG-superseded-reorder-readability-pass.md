---
trdd-id: QKWU26ZG
title: Reorder pass moves superseded atoms below the Superseded delimiter
column: todo
created: 2026-08-02T23:38:03+0200
updated: 2026-08-02T23:38:03+0200
current-owner: janitor-session
task-type: feature
severity: low
scope: project
release-via: publish
created-by: 57WJL5L2
npt: []
eht: []
implementation-commits: []
---

# The READABILITY layer of TRDD-57WJL5L2 — move superseded atoms below `## Superseded`

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative)

**Not started.** Split out of TRDD-57WJL5L2 per its own design refinement: the
CORRECTNESS layer shipped there (status-keyed default-exclude + `--include-superseded`
+ the two lint WARNs, commit cceb229) and is complete without this; the delimiter +
reorder are the READABILITY layer (humans see current facts first). The lint WARNs
(`superseded-atom-above-delimiter`, `superseded-atom-no-delimiter-heading`) already
fire — this card ships the thing that CLEARS them.

## The ask

A chore-procedure step (subconscious-agent work, NOT a new marker) that moves
`status: superseded` atoms below a canonical `## Superseded` heading on their own page
— verified lossless via the `verify_*` oracle (atoms MOVE, never deleted; lessons
travel; `atom_lessons_travel` is wired into the composites since c669107a).

## Design notes (decided at split time)

- **Home:** fold into an EXISTING chore's procedure rather than an 8th marker — the
  natural candidates are `janitor-memory-repair` (page-shape work; the WARNs are lint
  findings, and repair is the lint-clearing pass) or `janitor-memory-retro-lesson`
  (already touches superseded atoms per-page via the repair txn, TRDD-J3ZH3RSI).
  Decide when implementing; do NOT add a new marker/cadence key for this.
- **Delimiter spelling:** exactly `## Superseded` (the lint helper
  `superseded_heading_line` in memgrep is the SSOT — fence-aware).
- Also document the convention on the wikimem model page
  (`skills/janitor-memory-write/references/wikimem-model.md`) in the same change.

## Verification

- A fixture page with a superseded atom above the heading round-trips through the pass:
  atom sits below `## Superseded`, oracle green (zero knowledge loss), both lint WARNs
  clear, `memgrep validate` clean.
- A page with no superseded atoms is untouched.

## Notes and lessons learned
