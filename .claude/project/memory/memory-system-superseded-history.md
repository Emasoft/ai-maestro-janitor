---
name: memory-system-superseded-history
description: "why does a superseded atom about publish-globally still exist / what was the earlier claim about the publish-globally symlink ambiguity / superseded predecessor of ATOM-GLCB-AN5U / historical record of a corrected memory chore argument / demote don't delete correction protocol worked example"
ocd: 2026-06-13
lmd: 2026-09-03
metadata:
  node_type: memory
  type: project
  tier: component
  functionality: janitor
  originSessionId: memory-audit-draft
publish-globally: false
split-lineage: c89f02722a424b5385204031e5db35ce
---

# Memory-system superseded history (publish-globally chain)

Part of the [[memory-system]] functionality. The RETIRED predecessor atoms of
the `publish-globally-missing` reasoning chain, kept per the correction
protocol (demote, never delete): each carries a dated `[^N]`-style WHY and a
`superseded-by:` pointer forward to the next atom in the chain, ending at
ATOM-GLCB-AN5U, which now lives on [[memory-system-editor-gotchas]]. Split
out of [[memory-system]] 2026-09-03 to keep that page a navigable overview
instead of a dump.

## Superseded


^ATOM-31W8-NR3A [desc: "publish-globally is NOT a repair-gate defect and must never be added to repair_defect — memgrep decides it from FILESYSTEM state, so page text cannot split the two missing-cases", keywords: publish-globally-missing_never_drains lint_count_stuck_at_29 add_publish-globally_to_repair_defect widen_repair_defect_signature gate_and_arbiter_parity_publish-globally repair_chore_does_not_fix_publish-globally publish-globally_split_is_real_in_code_only zero_live_instances_of_an_enum_variant superseded_original_claim one_atom_holds_one_fact_split_it superseded_by_a_measured_correction, ocd: 2026-08-27, lmd: 2026-08-27, status: superseded, superseded-by: ATOM-GLCB-AN5U]

`memgrep lint` reports `publish-globally-missing` on PROJECT pages, and `repair_defect` (the
single-source repair-candidacy predicate) deliberately has NO check for it. That gap is CORRECT —
re-litigated and rejected 2026-08-27 (TRDD-AO8MPK5D, `efad7a99`); rejection recorded in
`memory_content_precheck.py` beside the janitor#260 one. Three independent reasons:

1. **Text cannot decide it even WITH the path.** `publish_globally_state` (`memory.rs:4878`) reads
   FILESYSTEM state — whether a USER-root symlink resolves to this page — and splits "field
   missing" into `MissingDefaultFalse` (no symlink → `false`) vs `MissingSymlinkImpliesTrue`
   (symlink present → `true`, evidence of intent). A text+path predicate cannot tell them apart,
   so it hands the agent a 50/50 guess whose wrong branch SILENTLY UN-PUBLISHES a page somebody
   deliberately published.
2. **The disagreement runs in the SAFE direction.** janitor#227 loops because it is gate-LOUD and
   arbiter-CLEAR; this is gate-SILENT and lint-loud, so it can never dispatch and never loops.
   Coverage shortfall, not the #227 class.
3. **It self-heals.** `atomic_write_page` (`memory.rs:2526`) is the SOLE write choke point and runs
   `normalize_page_until_clean` before AND after every write, unconditionally.

STALENESS SIGNAL: the count GROWING across releases means pages are being written OUTSIDE the
choke point (raw Edit-tool writes to PROJECT memory) — a bigger bug than the field. Re-open only
on that evidence. See [[ATOM on the scope=None fail-CLOSED trap]] before adding ANY scope-gated
check here.

^ATOM-MWID-C4CR [desc: "publish-globally is NOT a repair-gate defect and must never be added to repair_defect — memgrep decides it from FILESYSTEM state, so text cannot split the two missing-cases", keywords: publish-globally-missing_never_drains lint_count_stuck_at_29 add_publish-globally_to_repair_defect widen_repair_defect_signature gate_and_arbiter_parity_publish-globally repair_chore_does_not_fix_publish-globally pass_scope_label_to_a_precheck_predicate memory_chore_predicate_takes_no_path publish-globally_split_is_real_in_code_only zero_live_instances_of_an_enum_variant superseded_original_claim, ocd: 2026-08-27, lmd: 2026-08-27, status: superseded, superseded-by: ATOM-31W8-NR3A]

`memgrep lint` reports `publish-globally-missing` on PROJECT pages, and `repair_defect` (the
single-source repair-candidacy predicate) deliberately has NO check for it. That gap is CORRECT
and was re-litigated and rejected on 2026-08-27 (TRDD-AO8MPK5D, commit `efad7a99`); the rejection
is recorded in `memory_content_precheck.py` beside the janitor#260 one.

Three independent reasons, and the first is the one people miss:

1. **Text cannot decide it even WITH the path.** `publish_globally_state` (`memory.rs:4878`) reads
   FILESYSTEM state — whether a USER-root symlink resolves to this page — and splits "field
   missing" into `MissingDefaultFalse` (no symlink → write `false`) vs `MissingSymlinkImpliesTrue`
   (symlink present → write `true`, the symlink being evidence of intent). A text+path predicate
   cannot tell them apart, so it hands the agent a 50/50 guess whose wrong branch SILENTLY
   UN-PUBLISHES a page somebody deliberately published.
2. **The disagreement runs in the SAFE direction.** janitor#227 loops because it is gate-LOUD and
   arbiter-CLEAR. This is gate-SILENT and lint-loud: it can never cause a dispatch, so it can
   never loop or burn a token. Coverage shortfall, not the #227 class — do not reason about the
   two as the same bug.
3. **It self-heals.** `atomic_write_page` (`memory.rs:2526`) is the SOLE write choke point and runs
   `normalize_page_until_clean` before AND after every write, unconditionally. The flagged pages
   are simply pages nothing has written since the field was introduced.

The variant that looks cleanest is the worst: gating the check on a `scope=None` default would make
it the FIRST None-path in that module that SUPPRESSES a finding, where `repair_has_work` (~`:840`)
explicitly does the opposite (`if scope is None: return True`). Fail-OPEN is the house posture; a
scope-gated skip is fail-CLOSED and looks identical to a clean corpus.

STALENESS SIGNAL: the `publish-globally-missing` count GROWING across releases rather than
shrinking means pages are being written OUTSIDE the choke point (raw Edit-tool writes to PROJECT
memory) — a much bigger bug than the field. Re-open this only on that evidence.

## Governed by

- [[memory-system]] -- the functionality hub this page is one part of.

## See also

- [[memory-system]] -- the overview and parts map.
- [[memory-system-editor-gotchas]] -- the LIVE atom (ATOM-GLCB-AN5U) this
  history chain leads to.

## Notes and lessons learned
