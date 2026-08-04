---
trdd-id: QKWU26ZG
title: Reorder pass moves superseded atoms below the Superseded delimiter
column: complete
created: 2026-08-02T23:38:03+0200
updated: 2026-08-03T01:47:48+0200
current-owner: janitor-session
task-type: feature
severity: low
scope: project
release-via: publish
created-by: 57WJL5L2
npt: []
eht: []
implementation-commits: [5b5816e]
---

# The READABILITY layer of TRDD-57WJL5L2 — move superseded atoms below `## Superseded`

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-03

**COMPLETE — landed as commit 5b5816e.** Home decision resolved per the design notes:
the REPAIR chore (not retro-lesson, not an 8th marker) — the defect is page SHAPE,
repair is the lint-clearing pass, and retro-lesson's precheck only fires on
pointer-less atoms so a CONVERTED atom above the heading would never re-trigger it.
Shipped: the repair skill's new checklist entry + staged-edit step (create
`## Superseded` before Notes when missing; move superseded atom blocks below it
VERBATIM — reorder only, lessons stay pooled, never touch a valid atom);
`_page_needs_repair` mirrors memgrep's two WARN shapes (shared
`_SUPERSEDED_STATUS_RE`); the `## Superseded` convention documented on
wikimem-model.md beside the superseded-memory invariant. 128 precheck/maintenance +
88 skill-shape tests green. First REAL reorder run is observation-gated on a corpus
candidate appearing (none exists today). Ships via the blocked release train
(TRDD-AWXK0RFT).

**SUPERSEDED — do NOT carry forward:** "Not started."

---

Split out of TRDD-57WJL5L2 per its own design refinement: the
CORRECTNESS layer shipped there (status-keyed default-exclude + `--include-superseded` +
the two lint WARNs, commit cceb229) and is complete without this; the delimiter +
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
