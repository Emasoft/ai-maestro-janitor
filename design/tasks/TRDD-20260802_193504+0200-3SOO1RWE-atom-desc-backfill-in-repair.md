---
trdd-id: 3SOO1RWE
title: Repair pass backfills and validates the atom-level desc field
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

# Atom `desc` backfill + validation in the repair pass

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative)

**Not started.** Child 4 of 4 split out of TRDD-87RKBYJ8 (duty 2 — authoring-time REQUIRED
everywhere; the retroactive/validating half is MISSING). The cheapest of the four per the
2026-08-02 audit.

## The ask (parent duty 2)

Every ATOM's `desc:` must be present, ≤200 chars, AND a true summary. All authoring skills
REQUIRE it at write time; nothing validates or backfills it on EXISTING atoms.

## Verified facts (2026-08-02 audit, spot-checked first-hand)

- `verify_repair`'s `_REQUIRED_FM_KEYS` (`memory_edit_verify.py:1106`) checks ONLY the
  PAGE-level `description` key — no atom-level `desc:` check anywhere in repair.
- `memory_content_precheck.py` has zero `desc` work-detection (grep confirmed), so the repair
  chore never dispatches for a missing/oversized atom desc.
- memgrep lint validates desc SYNTAX when present (`atom-unquoted-desc`) but not presence/length
  semantics at repair time.

## Smallest shippable step (audit recommendation)

1. `repair_has_work` gains a cheap atom-desc scan (missing or >200 chars).
2. `verify_repair` gains the atom-level check: after a repair, every atom carries a quoted
   `desc:` ≤200 chars (the repair skill backfills from the atom's own body — summarize, never
   invent facts not in the body).
3. The repair skill documents the backfill procedure.

## Verification

- A fixture page with a desc-less atom dispatches repair; post-repair every atom has a valid
  desc; `verify_repair` refuses a "repair" that leaves one missing.
- No dispatch churn on a clean corpus.

## Notes and lessons learned
