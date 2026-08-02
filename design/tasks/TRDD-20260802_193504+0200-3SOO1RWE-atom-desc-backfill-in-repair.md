---
trdd-id: 3SOO1RWE
title: Repair pass backfills and validates the atom-level desc field
column: testing
created: 2026-08-02T19:35:04+0200
updated: 2026-08-02T20:05:00+0200
current-owner: janitor-session
task-type: feature
severity: medium
scope: project
release-via: publish
created-by: 87RKBYJ8
npt: []
eht: []
implementation-commits: [b26440a9]
---

# Atom `desc` backfill + validation in the repair pass

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative)

**✅ IMPLEMENTED 2026-08-02 20:05. Column `testing` — one real chore-driven backfill awaited
(publish-gated: the chore runs from the installed plugin cache).**

Shipped, all three steps + one defect found by measuring:
1. **SSOT check** `memory_edit_verify.atom_desc_violations(text)` — missing / empty /
   unquoted-PROSE / >200-char atom descs flag; quoted and unquoted CLEAN-SLUG (`[a-z0-9_]+`)
   pass — the bar mirrors memgrep's `desc_unquoted_prose` (memory.rs:3081) EXACTLY, verified
   against the Rust source first (a stricter Python bar would demand repairs the linter never
   asks for; a looser one would pass pages lint rejects). Fenced marker-shaped examples never
   flag. Wired into BOTH `verify_repair` (refusal reason — the completeness contract) and
   `_page_needs_repair` (scheduler precheck) — same SSOT, cannot drift. Safe under WN7M829Y's
   no-churn rule ONLY because step 3 makes repair able to fix it.
2. **Precheck** dispatches on the violation; refusal ledger + per-run caps bound the sweep.
3. **Repair skill** documents the backfill: summarize the atom's OWN body, never invent;
   quote unquoted-prose verbatim; tighten an over-cap desc without dropping facts.
4. **Defect found while measuring the blast radius:** a LOCAL page with DUPLICATE Notes
   headings made `_body_minus_lessons` RAISE (its by-design multi-page guard) — which would
   have crashed `repair_has_work` in the scheduler. `atom_desc_violations` now reports the
   duplicate-heading defect as the violation instead of propagating (an oracle returns,
   never raises).

**Measured corpus blast radius (2026-08-02):** 2 LOCAL pages/14 violations + 2 PROJECT/2 +
26 USER/123 = 30 pages/139 — bounded retroactive work the repair chore drains at its own
cadence; that queue IS duty 2's cleanup, not collateral.

Tests: 2 in `test_memory_edit_verify.py` (shape classifier incl. fence immunity; refuse →
backfill → pass) + 2 in `test_memory_content_precheck.py` (dispatch on desc-less; NO churn on
quoted/legacy-slug). Suites 116+84 green; ruff clean.

**NEXT ACTION (testing):** after the next publish, observe ONE real `[janitor-memory-repair]`
pass backfill a desc (oracle green) — then `complete`.

*(superseded original entry: "Not started. Child 4 of 4… cheapest of the four.")*

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
