---
trdd-id: DBQDGZT1
title: Y3B4HPTF closing scope claim covers arms its source reading did not
column: human_review
status: tasked
created: 2026-11-10T05:20:05+0100
updated: 2026-11-10T06:31:50+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: docs
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-10T05:20:05+0100
---

# Y3B4HPTF closing scope claim covers arms its source reading did not

## What is wrong

TRDD-Y3B4HPTF was closed `complete` on 2026-11-10 (commit 3fe27245, archived card) on this closing sentence, written into its Approval log:

> the residual class as stated ("an rc=0 run that writes no report on a NON-EMPTY staged set") is closed **for every path the hook takes except the mktemp-FAILURE branch**

An adversarial review found that sentence false as written, and reading `git-hooks/pre-commit` confirms it. Two independent defects in one clause:

1. **It conflates the paths that REACH the arm with the paths the hook TAKES.** The empty-report predicate `[ ! -s "$ubs_report" ]` sits at `git-hooks/pre-commit:155`, INSIDE the `0|1)` arm. The ubs artifact-delivery contract therefore governs exactly that arm and nothing else.
2. **It is false in fact.** The hook has an explicit `3)` arm at `git-hooks/pre-commit:170-174` — a path the hook takes, and not the mktemp branch. ubs exits 3 when it scans nothing (no supported source file in the staged set).

Both commits in that closing sequence hit the exit-3 arm. The hook printed, verbatim:

```
pre-commit: ubs — scanned nothing (exit 3, above: no supported source file in the staged set). Not a pass, not a failure; not blocked. [advisory stage]
```

So the mktemp-FAILURE branch was never the sole exception, and the card's own two live observations were from the one arm outside the contract the card was closing.

## Accurate form

The ubs delivery contract closes the residual class ("an rc=0 run that writes no report on a NON-EMPTY staged set") for the invocation shapes that REQUEST a report. An earlier revision said "for every path that reaches the `0|1)` arm … and nothing else", which was an uncited unit-of-analysis choice: `--report-json` is passed on the mktemp-SUCCESS path (git-hooks/pre-commit:91), a precondition ACROSS arms, not an arm. The exit-3 arm is outside the contract because ubs performs no scan and so has no report to deliver.

The substantive conclusion is NOT withdrawn, but it is INFERRED-INHERITED, not verified in this card: the ubs:8875-8884 citation was read in the TURN THAT CLOSED Y3B4HPTF, not re-read here. SCOPE, restored from the parent card: a source reading of 5.4.17, not a vendor statement; another version may differ. Weakened form: on the arm the predicate governs, an rc=0 run that requested a report has that report on disk unless 5.4.17's delivery contract is wrong. What is removed is a universal quantified over arms the source reading never covered.

EARLIER DRAFT, WITHDRAWN: this section was headed "Not a defect: exit 3 is distinguishable" and argued that the review's finding was refuted outright. Both that heading and that verdict are withdrawn; the corrected form follows.

## Partly refuted: exit 3 is distinguishable by MESSAGE, not by OUTCOME

The review claimed exit 3 "reproduces exactly that shape" of indistinguishable outcomes. That is RIGHT on the channel it named, and an earlier revision of this card wrongly stamped it FALSE ALARM. The `3)` arm prints a distinct diagnostic ("scanned nothing … Not a pass, not a failure; not blocked"), so a reader PARSING PROSE can tell it from a clean pass. But the arm contains no `exit`, so it falls through exactly as a clean pass does: both exit 0, both let the commit land. On the exit-STATUS channel the two remain indistinguishable. Accurate form: PARTLY REFUTED — distinguishable by message, not by exit status; the `*)` arm does block outright. The card's coverage gap is in its *scope sentence*, not in the hook's behaviour.

## Consequences

- TWO commit messages carry claims withdrawn by this card, and neither can be corrected without rewriting published history: `3fe27245` (the false universal) and `c96364db` (the "FALSE ALARM" verdict). Both stand as errata, and THIS card — not the frozen Y3B4HPTF — is where their corrections live. Flagged for the owner.
- The two live exit-3 observations must not be cited as end-to-end confirmation of the critical/advisory arms — exit 3 runs no scan.

## Why this is a separate card and not an edit

`git-hooks`-adjacent claim corrections belong on the owning card, but TRDD-Y3B4HPTF is archived and `trddgrep` refuses every write to an archived card, Approval log included ("archived cards are immutable, definitive history"). Per the terminal-column rule, new work is a new card. No code change is owed: `b72aff2a` implements every arm correctly.

## Cause

The same failure mode the card's own 2026-11-09 entries kept producing — a fresh universal generated while correcting the previous one. Root cause of the repeat: the closing entry generalised from the arm it had read the source for to arms it had not.

## Approval log

- 2026-11-10T05:20:05+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-10T06:31:50+0100 — column → human_review by main-agent@ai-maestro-janitor. The card's own work is complete — it is an errata record whose only remaining terminal condition is that the owner reads and acknowledges it. 'todo' was a false column under governance-trdd-kanban.md ('WIP must match capacity … an untrue column is worse than an unstarted card'): there is nothing to pull. Same reasoning already applied to JY0OBQZ4 one commit earlier.

## AUTHORITATIVE RECORD — consolidated corrections, 2026-11-10 (the same corrections also appear IN PLACE above, in Accurate form and in the section retitled 'Partly refuted'; this section is the record, and where the two copies differ, THIS section wins)

Findings against this card, APPLIED. (1) FALSE ALARM WITHDRAWN: the refutation confuted the MESSAGE, not the OUTCOME — the 3) arm (git-hooks/pre-commit:170-174) contains no exit, so exit 3 falls through exactly as a clean pass does (both exit 0, both let the commit land), and on the exit-STATUS channel they remain indistinguishable; accurate form is PARTLY REFUTED, distinguishable by message and not by exit status, and commit c96364db's FALSE ALARM wording is errata pointing here. (2) The parent card's SCOPE caveat (a source reading of 5.4.17, not a vendor statement; another version may differ) was dropped by this card and is RESTORED; the ubs:8875-8884 citation was read in the CLOSING turn, not in this turn, so it is INFERRED-INHERITED, not VERIFIED here. (3) 'governs exactly that arm and nothing else' was an uncited unit-of-analysis choice — --report-json is passed on the mktemp-SUCCESS path (git-hooks/pre-commit:91), a precondition ACROSS arms, not an arm; weakened to: the contract governs the invocation shapes that REQUEST a report, and the empty-report predicate sits inside the 0|1) arm. (4) The bare '10 measured states' figure, ENUMERATED: clean 0; warnings-only 0; critical 0 with findings printed; docs-only rc=3 to 0; empty index 0; ubs absent to 1; rc=2 to 1; rc=4 unknown to 1; report without totals to 1; mktemp failure to 0. (5) TERMINAL CONDITION, unstated before: no code change is owed and b72aff2a implements every arm correctly, so this card is COMPLETE when read and acknowledged by the owner; the errata is the deliverable, it is not a work item, and nothing should be pulled from it. (6) The exit-3 observations from the closing sequence exercised the one arm that runs no scan and are NOT end-to-end confirmation of the critical/advisory arms. (7) PROVENANCE of that ten-state list, which the review correctly said was misattributed — INFERRED-INHERITED, and stated only as narrowly as its source supports. Per the parent card's own 2026-11-09 entry there are TWO classes: the ordinary case (rc=0 with a valid report, and rc=1 with criticals) was measured with the REAL ubs, while at least one other class was produced by driving the STAGE with a SHIM ubs under a fresh TMPDIR, and the shim measurements establish the stage's response to an input class, not that real ubs emits it. An earlier revision of this item named WHICH four states were shimmed (rc=2, rc=4-unknown, report-without-totals, mktemp failure); that membership list was NOT in the source and is WITHDRAWN as an inference dressed as provenance. The source fixes the two-way split, not the per-state membership. (8) CONFIDENCE on the load-bearing inherited claims, marked per the verification rule: 'no code change is owed and b72aff2a implements every arm correctly' is INFERRED-INHERITED from the parent card's measurement record, not re-read here; so is the ten-state list, and so is the shim/real split in (7).
