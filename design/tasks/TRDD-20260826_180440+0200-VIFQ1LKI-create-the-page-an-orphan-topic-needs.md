---
trdd-id: VIFQ1LKI
title: Create the topic page an off-topic atom needs when none exists
column: testing
created: 2026-08-26T18:04:40+0200
updated: 2026-10-10T09:18:56+0200
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
implementation-commits: [91cd5534, be4e8fc4, 6ab9618e, ee149708]
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

- [x] Page creation requires a recorded 3-root survey showing no existing page owns the topic
- [x] The new page is minted through the write verbs with correct scope routing (UNSURE → LOCAL)
      and a `description:` carrying the SYMPTOM phrasings, not the jargon of the subject
- [x] The moved atom arrives via QDYQLM5V's verified two-page move — this card mints the target,
      it does not re-implement the move
- [x] A test drives an off-topic atom whose topic has no page and asserts a page is created; a
      second test drives one whose topic DOES have a page under a different name and asserts NO
      page is created
- [x] `uv run pytest -q`, `ruff check scripts tests`, `mypy scripts/ --ignore-missing-imports`
2026-10-05 — Landed in 91cd5534 (in v3.7.0); the survey-then-mint race (re-survey once on a mint refusal, plus one race test and the skill's race path) is not built, so the card returns to todo; set implementation-commits to 91cd5534.

## Approval log

- 2026-09-27T12:44:27+0200 — column → todo by user. blocker QDYQLM5V closed complete 2026-09-27 (stale blocker cleared per batch6 verdict) Cleared blocked-by (--clear-blocker override).
- 2026-10-10T08:41:41+0200 — column → testing. race path built at be4e8fc4; gate running; item 2 of the landing review still owed

## Implementation

2026-09-29 LANDED (commit 91cd5534, lean-worker, main-verified): relocate_survey_then_create in memory_content_precheck.py — 3-root array recall; empty mints via new-mem-topic (UNSURE→local, symptom-phrased description); hit returns the existing page, no creation; the move stays migrate-mem-atom. Skill documents the branch. 4 new tests, 8 relocate/survey green, ruff clean; incidental mypy fix in pre-tool-release-age-guard scoped-npm parse. Acceptance boxes 1-4 ticked by evidence; box 5 (gates) green. Moving to testing.
2026-09-29 landing review (HOLDS, 2 discharges before terminal): (1) the survey→mint race is closed only by new-mem-topic's refuse-to-overwrite, untested — the helper must catch that error and re-survey once, returning the now-existing page (turning the race into the hit-path), plus one race test; the skill's branch must document the race path. (2) LOW: the relocate token-cap evidence is worker-asserted (machine-local); quote the counter output on the next touch.
2026-09-29 Independent confirmation (main, second full-suite run 10m34s): 3 failed / 17624 passed, matching the worker's attribution — test_wikimem_spec_drift (prose verb, TRDD-JHHD3S4Z) + test_git_optional_locks_guard (staged_privacy_scan read-only git calls, TRDD-FWDZDB7W); the third slot varied between runs (roster test TRDD-DG2V7D5P in the worker's run, not mine) among the same pre-existing set — no failure in any file this card touched in either run. The 3 failures belong to their owning TRDDs' close-out, not this card.
2026-09-29 Review CURE discharged (2 parts). (1) SETTLING RERUN run (main, 6.4s): all three named files re-run at HEAD — test_detector_roster_completeness (DG2V7D5P), test_git_optional_locks_guard (FWDZDB7W), test_wikimem_spec_drift (JHHD3S4Z) — 3 failed / 42 passed. The third slot IS the roster test at this HEAD; the trio is now fully identified and none of the three touches a file this card changed. (2) WORDING CORRECTED: the earlier line's 'the third slot varied between runs ... among the same pre-existing set' was an overclaim — the tail -3 capture cut the third FAILED line, so variation was assumed, not observed. Observed: count matched (3), two names matched; the third is now confirmed by rerun.
2026-09-29 Terminal review round (REOPEN, wording CURES applied once, disclosed to user): the discharge's 'The third slot IS the roster test... confirmed by rerun... fully identified' claimed re-observation where the evidence supports INFERENCE only — main's run's uncaptured output is gone; the rerun proves current failure, not the earlier line's content. Corrected strength: identification is by rerun-plus-worker-capture inference — the worker's own contemporaneous full-suite run captured all three failing INCLUDING the roster test, making it the only candidate absent a full-suite-conditional fourth failure; the runs' HEADs differ by card-only .md commits (immaterial — none of the three tests reads design cards); the attributions (FWDZDB7W etc.) remain the worker's git log -S claims, not independently re-verified — the discharge only claims identification, which is its right scope.
2026-10-10 08:41: be4e8fc4 discharges item 1 of the 2026-09-29 landing review: a refused mint triggers one re-survey and a hit is returned as (False, page); one race test that sequences the REAL memgrep binary through a shell shim (it copies the competing page in after the first real recall); the relocate skill carries the same rule. The worker confirmed by a direct run that new-mem-topic refuses an existing page, and reported ruff, mypy, pyright clean and 180 tests passing in the test file; the main session read the whole diff. The full gate on be4e8fc4 writes reports/board/gate-be4e8fc4.txt and had not reported when this line was written; if it fails this card returns to dev. Item 2 of that review (quote the relocate token-cap counter output) is NOT done: the counter output is not on this machine's record that the main session could find without a search, so it stays owed. The card's fifth acceptance box (gates) rests on that gate result.
2026-10-10 08:58: 6ab9618e, from the review of be4e8fc4. GATE GREEN on be4e8fc4: ruff, mypy, pyright exit 0; 18282 passed, 2 skipped (reports/board/gate-be4e8fc4.txt); the gate on 6ab9618e writes reports/board/gate-6ab9618e.txt and had not reported when this was written. THE RACE IS NARROWED, NOT CLOSED: the mint is refused by page NAME and the re-survey matches by TOPIC, so a same-name page the topic query does not match still returns (False, None) and the caller records a refusal. Closing it would need the refused path taken from the verb's own output, which nobody has read; left open here, not carded. The race test now asserts the verb sequence recall, new-mem-topic, recall (it could pass before without the retry being reached); the main session re-ran the five duty-15 tests after reading the diff (5 passed) and the worker ran the race test five times in a row (5 passed). The competing page in that test is a hand-written valid page, not one minted by the verb. BOX STATE, corrected: the line of 2026-09-29 says boxes 1 to 4 were ticked by evidence, but all five boxes were unticked in the file today. Ticked now on what the main session read today: box 1 (the function surveys every given root before any mint) and box 4 (both tests read: lines 2296 to 2338 of the test file). NOT ticked: box 2 (the description's symptom phrasing is the caller's and was not read), box 3 (the move path was not read today), box 5 (waits for the gate on 6ab9618e). ITEM 2 of the 2026-09-29 landing review (quote the relocate token-cap counter output): no counter output was searched for or found; what was measured today is wc -c on skills/janitor-memory-relocate/SKILL.md, 8012 bytes, about 2000 tokens at four bytes a token, against the owner's limit of 5000; taken as discharging the item by the main session's decision, with the caveat that no tokenizer was run.
2026-10-10 09:13: GATE GREEN on 6ab9618e (ruff, mypy, pyright exit 0; 18282 passed, 2 skipped; reports/board/gate-6ab9618e.txt). BOXES, from the review of 6ab9618e and one read of skills/janitor-memory-relocate/SKILL.md lines 60 to 112 by the main session: box 1 UNTICKED, because it asks for a RECORDED three-root survey and the skill tells the agent to record the survey only when it finds a page (step 2), not when it is empty (step 3); box 2 ticked (step 3 mints through new-mem-topic with scope routing, UNSURE to local, and a description of at least 15 symptom phrasings); box 3 ticked (step 4 and the MOVE branch hand the minted page to migrate-mem-atom; nothing here re-implements the move); box 5 ticked on the gate above. ITEM 2 of the 2026-09-29 landing review is WAIVED by the main session with the byte measurement of the 08:58 line, not discharged: no counter output was found and no tokenizer was run. NEW FACT: relocate_survey_then_create has no caller outside the tests (grep of scripts, skills, agents, commands), so agents follow the skill text by hand; the code fix protects a future caller and the skill sentence is what changes behaviour today. The name-versus-topic hole and the docstring rewrap are now TRDD-BAK8B3C0; the words 'left open here, not carded' in the 08:58 line are superseded. TO CLOSE THIS CARD: one sentence in the skill's step 3 telling the agent to record the empty survey in its report, shipped with the next code batch (not alone: a one-sentence edit does not earn its own full-suite run); then box 1 and the wave 3 closing rule.
2026-10-10 09:16, corrections from the review of 957985a3: 'has no caller' should read 'no caller found by a grep of scripts, skills, agents and commands'. Boxes 2 and 3 rest on the relocate skill's TEXT (read before the 09:09 clear and seen after it through the compacted context), because no caller exists to read; box 2's scope routing inside the helper itself rests on the 2026-09-29 worker line, and box 3's word 'verified' is QDYQLM5V's own claim, not re-checked here. The skill sentence for box 1 now has a carrier: TRDD-BAK8B3C0's change.
2026-10-10 09:19: ee149708 adds to step 3 of the relocate skill's CREATE section 'Record in your report that the three-root survey was empty before you mint' (step 2 already records a hit), so box 1 is ticked on the diff the main session read. All five boxes are ticked. It stays in testing until the full gate on ee149708 reports (reports/board/gate-ee149708.txt). CLOSING RULE then: (1) the commits are on main; this card has no release-via field, and the skill text reaches agents only with a release; (2) pinning tests to re-run by name: the five duty15 tests in tests/test_memory_content_precheck.py; (3) FIELD CASE UNOBSERVED: no live relocate pass has minted a page.
