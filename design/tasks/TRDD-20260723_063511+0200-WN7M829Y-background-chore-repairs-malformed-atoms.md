---
trdd-id: WN7M829Y
title: The janitor background chore retroactively repairs malformed atoms via supersession
column: todo
created: 2026-07-23T06:35:11+0200
updated: 2026-07-23T08:05:00+0200
current-owner: claude-ai-maestro-janitor
task-type: feature
severity: medium
relevant-rules: [1]
npt: [DOJ2LE1G]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-23

**NPT DOJ2LE1G is DONE + LIVE** (add-lesson --supersedes + the 4 lint checks + binary
installed), so the retroactive repair is now UNBLOCKED and TOOLING-READY. This is the only
remaining piece of the wikimem-authoring plan; Phases 1/2/3 shipped.

**Scope corrected while implementing (do NOT hack the scheduler):** the four defect classes do
NOT map cleanly onto the existing repair/atomize passes, so `repair_has_work` must NOT be
extended to flag them — that would dispatch repair passes that cannot fix them (churn):
- `unquoted-desc` — mechanically fixable (quote the value). REPAIR-class.
- `oversized-atom` (36 corpus-wide) — DECOMPOSITION, judgment-heavy; not a repair fix. Needs the
  atomize pass OR `memgrep migrate` to split one atom into several — a NEW editorial capability.
- `empty-lesson-body` / `superseded-without-body` — may be UNRECOVERABLE (the old body/why can be
  gone). Where recoverable, supersede; where not, the honest fix is to flag for a human, not invent.

**So the retroactive sweep is genuine EDITORIAL-AGENT work with real shared-corpus blast radius,
not more scheduler code.** The corpus currently carries **36 oversized + 4 unquoted-desc** (0
empty-lesson-body, 0 superseded-without-body — the new gate keeps it that way going forward).

**NEXT ACTION (run deliberately, ideally with the user aware — shared memory):** dispatch the
`janitor-memory-subconscious-agent` on a bounded scope with a per-class policy —
unquoted-desc → in-place repair (quote); oversized → decompose via atomize/`migrate` (judgment);
empty/superseded-without-body → supersede if the old fact is recoverable, else flag. Surface
progress; never delete an atom. This is the piece to do with the USER in the loop, not a silent
autonomous batch. Detection is already available (`memgrep lint <scope>` flags all four).

## The ask

The malformed atoms already in the corpus (unquoted `desc`, body-less lesson, oversized atom,
superseded-without-body) must be FIXED retroactively by the background janitor memory chore —
never by deleting them. A wrong atom gets `status: superseded` + a lesson reference that
embeds its verbatim old body; only pure typos / formatting errors may be edited in place.

## The fix (this TRDD's scope)

1. **Detect.** `scripts/detectors/wikimem-syntax.py` + `scripts/wikimem_syntax_lint.py` gain
   the four defect classes from DOJ2LE1G, so a malformed atom SURFACES as drift (never
   mutating anything — the detector only reports).
2. **Repair.** The `janitor-memory-subconscious-agent` REPAIR/ATOMIZE passes (the
   `janitor-memory-{repair,atomize}` skills) act on the due scope:
   - a pure typo / formatting error (e.g. a missing quote the write verbs would have added) →
     an in-place REPAIR transaction (`--op repair`), which `verify_repair` proves lossless;
   - a WRONG fact → the supersession protocol: `add-lesson --supersedes <atom>` demotes the
     atom and records the correction as a dated lesson. NEVER a delete.
   - an OVERSIZED atom → decompose into smaller atoms via an ATOMIZE/split transaction, with
     the lessons travelling to the correct child atom (VJCMZ2OP / the `migrate` verb).
3. **Prove it.** Every repair is a `memory_txn` transaction gated by the `verify_*` oracle in
   `memory_edit_verify.py`; the pass ends with `memgrep validate && memgrep lint` on each
   touched page. A pass that cannot prove no-knowledge-lost ABORTS and flags for a human.

## Boundary

The chore FIXES what the deterministic oracle can prove safe and FLAGS the rest — it never
deletes an atom, never invents a `WHY` for a supersession it cannot source, and never
reorganises structure beyond the flagged defect (that is the separation-of-powers rule: the
janitor reorganises + surfaces, the agent corrects content).

## Verification

- A seeded corpus with one of each defect class: the detector surfaces all four; the repair
  pass fixes the typo in place and supersedes the wrong-fact atom (old body preserved).
- No atom is ever deleted by the pass (grep the transaction journal for deletes → only
  merge/split-legitimate ones).
- `verify_repair` / `verify_atomize` green on every applied transaction; `pytest` + `ruff`
  green.

## Notes and lessons learned
