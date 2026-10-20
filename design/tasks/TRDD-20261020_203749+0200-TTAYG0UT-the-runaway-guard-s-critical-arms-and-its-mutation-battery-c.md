---
trdd-id: TTAYG0UT
title: The runaway guard's critical arms and its mutation-battery claim are not enforced by the suite
column: todo
status: tasked
created: 2026-10-20T20:37:49+0200
updated: 2026-10-20T20:37:49+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: maestro
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-20T20:37:49+0200
---

# The runaway guard's critical arms and its mutation-battery claim are not enforced by the suite

THE MUTATION CLAIM IN COMMIT a6727394 IS NOT ACCURATE, and the number is the load-bearing part.

MEASURED on 2026-10-20 with a 17-mutation battery over scripts/lib/runaway_guard.py, every mutation applied by literal string replacement, the file restored byte-exactly (sha256 f7ecb4b8 verified after every run), and tests/test_runaway_guard.py as the victim: 12 of 17 CAUGHT, 5 SURVIVED. A second round of 16 further mutations (corrected anchors) caught 10, 6 survived. Across both rounds: 22 of 33 caught, 11 survived.

THE SURVIVING MUTATIONS, and each one is a REAL GAP in the suite rather than a redundancy: the swap bar 95 -> 100 (no test asserts the DEFAULT value, so the calibration can drift by 5 points silently); the free-memory WARNING arm deleted (no test exercises free_warn, so the elevated tier can lose that arm with the suite green); the compressor WARNING arm deleted (same); the free-memory CRITICAL arm deleted (the disjunctions free-memory arm is untested, so the very change that made the kill path armable can be undone); the etime parsers unparseable -> 999999 (the "0 is the safe direction" claim in its own docstring is untested — a parser accident would make a 2-second-old process look ancient); the "largest victim wins" rule replaced by "first victim wins" (the assertion exists but the MUTATION SURVIVES because the test three rows are already in descending RSS order, so first == largest — the fixture cannot tell the two rules apart); the ancestry walk claude.exe branch dropped; the ancestry walk 64-level cap cut to 1; the interactive-clause regex made case-sensitive; and the swap ratio off-by-one.

THE LAST TWO ARE THE ONES THAT MATTER FOR SAFETY. "The largest victim wins" is the rule that decides WHICH process dies, and the test fixture makes it indistinguishable from "the first one in ps output" — a ps output whose row order changed would silently change the victim. The ancestry cap of 64 -> 1 survives because every ancestry fixture is one level deep, so the walks depth is untested: a chain that legitimately needs three levels (a process -> its parent -> a wrapper -> claude) would be REFUSED as unattributable with the suite green, which is a safety-preserving failure but a silent one.

WHY THIS MATTERS FOR THE COMMIT MESSAGE. Commit a6727394 says "The mutation battery is now 15 mutations with 14 caught; the one that survives is the over-refusing direction, and it survives because the rule is REDUNDANT with the basename check, which is recorded in the test rather than hidden." The MEASURED count is 22 of 33 with ELEVEN survivors, and only ONE of them is the documented redundant over-refusing rule. The other ten are unrecorded gaps, and one of them (the victim-selection rule) is the rule that decides who dies. A commit message that understates its own mutation result is worse than one that overstates it, because a reader trusts the number and stops looking.

THE FIX, and it is the same shape as the three vacuous tests this cards sibling already found: each surviving mutation needs a test that makes the MUTATED RULE the only thing that can decide the outcome. Concretely — the victim-selection test needs a fixture whose rows are NOT in descending RSS order; the ancestry test needs a chain three levels deep; the free-memory and compressor warning arms each need a case where THAT arm is the only one over its bar; the free-memory critical arm needs a case where free memory is the ONLY bad reading; the etime parser needs a case asserting an unparseable age is 0; and the swap bars DEFAULT needs pinning.

ACCEPTANCE: every mutation in the recorded battery FAILS the suite, or the survivor is documented in the TEST as a deliberate redundancy with the reason stated (the pattern the repo already uses for the over-refusing rule); the victim-selection fixture is order-independent; the ancestry fixture is deeper than one level; and the commit messages mutation count matches a measured run.
## Approval log

- 2026-10-20T20:37:49+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
