---
trdd-id: I4MOD020
title: C30 — drop precheck repair branches
column: backburner
status: tasked
created: 2026-10-01T19:45:17+0200
updated: 2026-10-10T12:08:22+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: refactor
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T19:45:17+0200
blocked-by: []
pre-block-column: todo
blocker-probe: [trddgrep, why, I4MOD020]
blocker-holds-if: not-match:READY
---

# C30 — drop precheck repair branches

Derived from TRDD-DSN035UN (approved plan v4, 2026-10-01), card C30, wave W3.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-09

NEXT ACTION: C30 is a DESIGN DECISION, not a mechanical drop. Re-attempt ONLY after one of: (a) a design card exists for a lint-driven discovery surface feeding C22-style fixers, or (b) repair_has_work is extended to consult memgrep lint for fixer-backed codes. Until then the two precheck repair branches STAY (they are the standing discovery trigger; review F1 confirmed). The reverted implementation is preserved in git history only (read it with: git show 583e2e60:design\/specs\/c30-reverted-implementation\/20261009_c30-reverted-implementation-patch.diff; removed from the working tree 2026-10-09 because the file made the release validator report 9 MAJOR findings) — KNOWN-REJECTED evidence, do NOT apply without the discovery-trigger decision. Owner decides the path.

Writes (exclusive): scripts/lib/memory_content_precheck.py, its tests
Task: Drop repair_defect branches whose defect now has a SAFE fixer
Verify: A fixture run through memgrep lint, then the predicate, finds no SAFE-class defect
Depends on: C22 — SATISFIED-THEN-COUPLED, not blocking (disposition in the Approval log, 2026-10-09; the coupling is that this card's Pass-1 run is the evidence-event shape C22's gate awaits — tracked by the escalation clause on JD2QR5SQ, read the count there)
Conflict rule: this card may write ONLY the files listed under Writes.

## Approval log

- 2026-10-01T19:45:17+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01T19:46:15+0200 — column → blocked by main-agent@ai-maestro-janitor. waits on JD2QR5SQ per DSN035UN wave order
- 2026-10-08 (probe caveat, corpus sweep): this why-probe's holds-if is not-match:READY against trddgrep why output — two known ceilings: (1) a future blocker card whose TITLE contains the word READY false-unblocks this card (grep is not column-aware here); (2) the zero-open-prereq->READY transition was never observed on a flipping card (endpoints only) — trddgrep may never print READY after an archived blocker (known tooling gap). Treat a probe release as a PROMPT TO RE-VERIFY the chain, not proof of unblocked.
- 2026-10-09T05:31:42+0200 — column → todo. JD2QR5SQ's dependency shape is a completion-event coupling, not a hard blocker: C22's gate needs a DEPENDENT to run Pass 1 on a real root — C30 IS that dependent, so blocking C30 on C22 completes a recorded deadlock (found by the verification review on 49261c98). The freeze is treated as lifted (agent inference, owner may correct). C30 unblocked; its own Pass-1 run is C22's awaited evidence.
2026-10-09 dependency disposition (per the review on 6e450b80): the body 'Depends on: C22' is SATISFIED-THEN-COUPLED, not blocking — C22's code exists (installed binary 4ecdbc3 carries S1-S4) and the coupling is that C30's Pass-1 run is the evidence EVENT SHAPE C22's gate awaits. Evidence expectation corrected: on the present corpus (measured 2026-10-09, zero fixer-backed findings on all three real roots) a Pass-1 run here has nothing to refuse — a zero-refusal outcome is the already-ruled clean-corpus case, tracked by the escalation clause on JD2QR5SQ — read the count there; NOT a pending mystery. The work itself (dropping precheck repair branches with SAFE fixers) is unblocked and developable.
- 2026-10-09T05:53:46+0200 — column → dev. unblocked per 2026-10-09 SATISFIED-THEN-COUPLED disposition; fan-out worker starts
- 2026-10-09T09:26:00+0200 — implementation landed (coordinator-executed after 3 stalled worker attempts; report reports_dev/20261009_081500+0200-i4mod020-c30-drop-precheck-branches.md): dropped no-notes-heading + superseded-misplaced branches from repair_defect (both fixer-owned per fixer_for registry), atom-desc KEPT (covers non-fixerable missing/over-cap descs); _SUPERSEDED_HEADING orphan deleted; 9 fire fixtures repointed notes=False→tier=banana; 196 scoped tests pass, ruff clean; card-verify clause met (lint finds the defect, precheck yields zero candidates — clean-corpus zero-refusal case per the JD2QR5SQ escalation ruling)
- 2026-10-09T09:26:45+0200 — column → testing. implementation landed, scoped tests green; full-suite gate runs in main session before commit
- 2026-10-09T09:45:00+0200 — IMPLEMENTATION REVERTED after the adversarial review (fork verdict: all 5 findings accepted, F1 CONFIRMED blocker). F1: repair_has_work IS the standing discovery trigger for the repair dispatch — dropping the two branches strands fixer-owned defects (missing-Notes, superseded-misplacement) with NO trigger: precheck yields zero candidates, no dispatch, so Pass 1 never runs on them and the fixers are dead code in the standing pipeline. The card-verify 'zero candidates' result was the failure signature, read as success. F2: _CODE_COVERAGE rows would have become uncatchable lies; F3: verify_repair still requires the Notes heading, so the docstring's no-drift invariant would be false. Exit (a) taken: reverted to HEAD (patch preserved at reports_dev/20261009_c30-reverted-implementation-patch.diff, 320 lines). ROOT PREMISE WRONG: 'drop the branch when a fixer exists' holds only if a standing trigger feeds the fixer — here the branch IS the trigger. Re-dispatch path: EITHER keep branches until C22-style fixers gain a lint-driven discovery surface (new card), OR extend repair_has_work to consult memgrep lint for fixer-backed codes — a design decision, not a mechanical drop. Card returns to todo pending that decision.
- 2026-10-09T09:38:15+0200 — column → todo. implementation reverted per adversarial review F1 (pipeline hole); needs a design decision on the fixer discovery trigger before re-attempt
2026-10-09T10:05:00+0200 — patch given a git-restorable home (review F2): reports_dev copy is now ALSO at design/specs/c30-reverted-implementation/20261009_c30-reverted-implementation-patch.diff (git-tracked). NEXT ACTION for re-dispatch (decision, not mechanical drop): EITHER mint a design card for a lint-driven discovery surface feeding C22-style fixers (then this card's drop becomes safe), OR extend repair_has_work to consult memgrep lint for fixer-backed codes; owner decides which path.
2026-10-09T10:55:00+0200 — record correction on 583e2e60: the STATE block sits after the Derived-from line and BEFORE the Writes/Task/Verify lines (it splits the intro block), not immediately after the title. The body Task/Verify lines still describe the rejected framing; the STATE block supersedes them per TRDD governance. reports_dev twin renamed to *.STALE-REVERTED-DO-NOT-APPLY-use-design-specs-copy so the warning sits at the grep surface (review 4 finding 1: a README sentence on the tracked side never reaches a reports_dev grep).
2026-10-09 reading note (review of 77a7d06a): this card's 2026-10-09 dependency disposition calls a zero-refusal Pass-1 outcome 'the already-ruled clean-corpus case'. That phrase states an EXPECTATION (a clean corpus gives the fixers nothing to refuse); it does NOT say C22's (JD2QR5SQ) gate accepts a zero-refusal run. C22's gate still needs a pipeline dispatch with an observed refusal.
2026-10-09 — the tracked patch file is REMOVED from the working tree: cpv-remote-validate --strict (v5.16.2) reported 9 MAJOR TOOL_SHADOW findings on it (the diff quotes test code), which would block every publish. It stays restorable from git: git show 583e2e60:design/specs/c30-reverted-implementation/20261009_c30-reverted-implementation-patch.diff (320 lines, verified). The README beside it now gives that command. Earlier log lines naming the design/specs path as the live location are superseded by this one.
2026-10-10 12:06 DECISION by the main session under the owner mandate of 2026-10-09 ('decide yourself'), wave 6 card 2, no code: NEITHER path is taken and the two precheck repair branches STAY. Facts it rests on, all from this card's own record of 2026-10-09: the branches (no-notes-heading, superseded-misplaced) are the standing discovery trigger of the repair dispatch; dropping them left the fixers with no trigger (review F1, confirmed, implementation reverted); path (a), a lint-driven discovery surface, and path (b), extending repair_has_work to consult memgrep lint, each add a new mechanism whose only purpose is to make deleting two working branches safe; no defect, cost or user-visible behaviour is attached to keeping them; and the corpus measured on 2026-10-09 had zero fixer-backed findings on all three roots, so there is nothing to measure the two paths on. The scratch-corpus comparison the drain card planned is therefore not run: it would compare two ways of doing something that does not need doing. DATED REASON FOR BACKBURNER: pull this card only if the precheck and the lint fixers are seen to DISAGREE on a real page (one flags a defect the other does not), which is the only harm duplication can cause here. The parent plan TRDD-DSN035UN's line for C30 should read 'not dropped, by decision'.
- 2026-10-10T12:06:06+0200 — column → backburner. decision: the two precheck branches stay; both drop paths add a mechanism only to delete working code
2026-10-10 12:08 corrections from the review of cb8068a1: (1) the decision above SUPERSEDES the STATE block's 'Owner decides the path', under the owner mandate of 2026-10-09; the owner may reverse it. (2) 'no defect, cost or user-visible behaviour is attached to keeping them' was NOT verified against the parent plan's intent: TRDD-DSN035UN names C30 only in its derived-card list and gives no reason there; the reverted review's F2 and F3 (coverage rows, a docstring invariant) suggest drift between precheck and fixers is the cost, unmeasured. (3) The decision was taken without the scratch-corpus comparison the drain card had planned; it rests on this card's 2026-10-09 record, and the corpus figure there is a day old. (4) The pull condition has no detector; it can fire only if someone notices. Nothing was built or removed, so the decision is fully reversible. (5) TRDD-DSN035UN was not edited.
