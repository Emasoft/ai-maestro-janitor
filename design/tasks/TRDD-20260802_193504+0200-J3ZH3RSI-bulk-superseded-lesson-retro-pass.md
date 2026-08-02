---
trdd-id: J3ZH3RSI
title: Bulk retro-pass converting already-superseded atoms into lesson form
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

# Bulk superseded→lesson retro-conversion (the 7th memory-maintenance marker)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative)

**Not started.** Child 3 of 4 split out of TRDD-87RKBYJ8 (duty 9 — the per-edit half EXISTS,
the bulk half is MISSING).

## The ask (parent duty 9)

Every SUPERSEDED atom must carry the lesson form (**DO NOT X, BECAUSE why, DO Y instead**,
old TRDDs still linked). The UPDATE INVARIANT (`janitor-memory-update` SKILL) already converts
at the moment of a fresh correction — but nothing re-scans EXISTING pages for atoms that are
already superseded-but-not-yet-lesson-form.

## Verified facts (2026-08-02 audit)

`memory-maintenance.py` lists exactly 6 chore markers (split/repair/atomize/harvest/
consolidate/conflict) — no retro-lesson marker; no scheduled chore scans for
`status: superseded` atoms lacking the DO-NOT/BECAUSE/INSTEAD shape.

## Smallest shippable step (audit recommendation)

1. A `retro_lesson_has_work(root)` precheck in `memory_content_precheck.py` (cheap scan for
   superseded-status atoms whose body lacks the lesson shape).
2. A 7th `[janitor-memory-retro-lesson]` marker in `memory-maintenance.py` + the heartbeat
   protocol row, dispatching the subconscious agent with a bounded per-run cap.
3. The chore procedure (skill): convert via `add-lesson --supersedes` (embeds the verbatim old
   body — non-destructive); where the WHY is unsourceable from commits/TRDDs, FLAG for a human
   — NEVER invent a WHY (the commit-discipline rule's provenance chain is the only source).

## Verification

- A fixture page with a superseded-not-lesson atom gets converted, oracle green, WHY sourced
  from the linked TRDD/commit; an unsourceable WHY is flagged, not fabricated.
- The precheck returns False on a clean corpus (no churn dispatches).

## Notes and lessons learned
