---
trdd-id: VIFQ1LKI
title: Create the topic page an off-topic atom needs when none exists
column: todo
created: 2026-08-26T18:04:40+0200
updated: 2026-10-05T10:57:06+0200
current-owner: janitor-main-session
task-type: feature
project-id: ai-maestro-janitor
scope: project
severity: minor
min-approval-requirement: none
labels: [wikimem, memgrep, memory-maintenance, atomize]
parent-trdd: 87RKBYJ8
blocked-by: []
npt: []
eht: []
implementation-commits: [91cd5534]
relevant-rules: []
pre-block-column: 
status: tasked
---

# Duty 15 — if an off-topic atom's topic has NO page yet, CREATE that page

Split out of **TRDD-87RKBYJ8** per its own rule.

**The duty, verbatim:** If an off-topic atom's topic has **no page yet**, CREATE that page.

## Genuinely blocked, and the blocker is named

`blocked-by: [QDYQLM5V]` (duty 14, the MOVE). This duty is the else-branch of that one: 14 moves
an off-topic atom to the page that owns its topic, and 15 handles the case where no such page
exists. Building the create path before the move path means building a page-minting rule with no
caller and no way to test the decision that reaches it.

Recorded as `blocked-by` rather than left as an undated note, because the kanban rule is explicit
that a card sitting still needs a named blocker that is itself open — otherwise it is stalled, not
parked.

## ⚠ SURVEY before minting a page

The standing memory rule says so directly for methodology pages, and the reason generalises: a new
page whose subject is already covered under a different name is the near-synonym failure duty 10
exists to undo. So creation is the LAST resort, after a recall across ALL THREE scope roots —
composed into an array, because a single-root recall returns a confident empty indistinguishable
from a real absence (measured twice on 2026-08-26; `ATOM-W99A-N60G`).

## Acceptance

- [ ] Page creation requires a recorded 3-root survey showing no existing page owns the topic
- [ ] The new page is minted through the write verbs with correct scope routing (UNSURE → LOCAL)
      and a `description:` carrying the SYMPTOM phrasings, not the jargon of the subject
- [ ] The moved atom arrives via QDYQLM5V's verified two-page move — this card mints the target,
      it does not re-implement the move
- [ ] A test drives an off-topic atom whose topic has no page and asserts a page is created; a
      second test drives one whose topic DOES have a page under a different name and asserts NO
      page is created
- [ ] `uv run pytest -q`, `ruff check scripts tests`, `mypy scripts/ --ignore-missing-imports`
2026-10-05 — Landed in 91cd5534 (in v3.7.0); the survey-then-mint race (re-survey once on a mint refusal, plus one race test and the skill's race path) is not built, so the card returns to todo; set implementation-commits to 91cd5534.

## Approval log

- 2026-09-27T12:44:27+0200 — column → todo by user. blocker QDYQLM5V closed complete 2026-09-27 (stale blocker cleared per batch6 verdict) Cleared blocked-by (--clear-blocker override).

## Implementation

2026-09-29 LANDED (commit 91cd5534, lean-worker, main-verified): relocate_survey_then_create in memory_content_precheck.py — 3-root array recall; empty mints via new-mem-topic (UNSURE→local, symptom-phrased description); hit returns the existing page, no creation; the move stays migrate-mem-atom. Skill documents the branch. 4 new tests, 8 relocate/survey green, ruff clean; incidental mypy fix in pre-tool-release-age-guard scoped-npm parse. Acceptance boxes 1-4 ticked by evidence; box 5 (gates) green. Moving to testing.
2026-09-29 landing review (HOLDS, 2 discharges before terminal): (1) the survey→mint race is closed only by new-mem-topic's refuse-to-overwrite, untested — the helper must catch that error and re-survey once, returning the now-existing page (turning the race into the hit-path), plus one race test; the skill's branch must document the race path. (2) LOW: the relocate token-cap evidence is worker-asserted (machine-local); quote the counter output on the next touch.
2026-09-29 Independent confirmation (main, second full-suite run 10m34s): 3 failed / 17624 passed, matching the worker's attribution — test_wikimem_spec_drift (prose verb, TRDD-JHHD3S4Z) + test_git_optional_locks_guard (staged_privacy_scan read-only git calls, TRDD-FWDZDB7W); the third slot varied between runs (roster test TRDD-DG2V7D5P in the worker's run, not mine) among the same pre-existing set — no failure in any file this card touched in either run. The 3 failures belong to their owning TRDDs' close-out, not this card.
2026-09-29 Review CURE discharged (2 parts). (1) SETTLING RERUN run (main, 6.4s): all three named files re-run at HEAD — test_detector_roster_completeness (DG2V7D5P), test_git_optional_locks_guard (FWDZDB7W), test_wikimem_spec_drift (JHHD3S4Z) — 3 failed / 42 passed. The third slot IS the roster test at this HEAD; the trio is now fully identified and none of the three touches a file this card changed. (2) WORDING CORRECTED: the earlier line's 'the third slot varied between runs ... among the same pre-existing set' was an overclaim — the tail -3 capture cut the third FAILED line, so variation was assumed, not observed. Observed: count matched (3), two names matched; the third is now confirmed by rerun.
2026-09-29 Terminal review round (REOPEN, wording CURES applied once, disclosed to user): the discharge's 'The third slot IS the roster test... confirmed by rerun... fully identified' claimed re-observation where the evidence supports INFERENCE only — main's run's uncaptured output is gone; the rerun proves current failure, not the earlier line's content. Corrected strength: identification is by rerun-plus-worker-capture inference — the worker's own contemporaneous full-suite run captured all three failing INCLUDING the roster test, making it the only candidate absent a full-suite-conditional fourth failure; the runs' HEADs differ by card-only .md commits (immaterial — none of the three tests reads design cards); the attributions (FWDZDB7W etc.) remain the worker's git log -S claims, not independently re-verified — the discharge only claims identification, which is its right scope.
