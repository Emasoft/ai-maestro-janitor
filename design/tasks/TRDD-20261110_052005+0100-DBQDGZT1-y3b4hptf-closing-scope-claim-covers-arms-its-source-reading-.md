---
trdd-id: DBQDGZT1
title: Y3B4HPTF closing scope claim covers arms its source reading did not
column: todo
status: tasked
created: 2026-11-10T05:20:05+0100
updated: 2026-11-10T05:45:29+0100
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

The ubs delivery contract closes the residual class ("an rc=0 run that writes no report on a NON-EMPTY staged set") **for every path that reaches the `0|1)` arm**. The exit-3 arm is outside that contract because ubs performs no scan and so has no report to deliver.

The substantive conclusion holds and is NOT withdrawn: rc=0 with a report requested and not delivered cannot occur on the arm the predicate governs, because ubs 5.4.17 forces `status=2` when a requested `--report-json` artifact is missing (`ubs:8875-8884`, cited by the card). What is removed is a universal quantified over arms the source reading never covered.

## Not a defect: exit 3 is distinguishable

The same review further claimed exit 3 "reproduces exactly that shape" of indistinguishable outcomes. **Refuted by the source.** The `3)` arm prints a distinct diagnostic that names the state ("scanned nothing … Not a pass, not a failure; not blocked"), and the `*)` arm blocks outright. An agent reading the hook's output can tell exit 3 from a clean pass. The card's coverage gap is in its *scope sentence*, not in the hook's behaviour.

## Consequences

- The false universal is also baked into commit `3fe27245`'s message. It cannot be corrected without rewriting published history, so it stands as errata pointing here. Flagged for the owner.
- The two live exit-3 observations must not be cited as end-to-end confirmation of the critical/advisory arms — exit 3 runs no scan.

## Why this is a separate card and not an edit

`git-hooks`-adjacent claim corrections belong on the owning card, but TRDD-Y3B4HPTF is archived and `trddgrep` refuses every write to an archived card, Approval log included ("archived cards are immutable, definitive history"). Per the terminal-column rule, new work is a new card. No code change is owed: `b72aff2a` implements every arm correctly.

## Cause

The same failure mode the card's own 2026-11-09 entries kept producing — a fresh universal generated while correcting the previous one. Root cause of the repeat: the closing entry generalised from the arm it had read the source for to arms it had not.

## Approval log

- 2026-11-10T05:20:05+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## CORRECTION on adversarial review — 2026-11-10

Findings against this card, APPLIED. (1) FALSE ALARM WITHDRAWN: the refutation confuted the MESSAGE, not the OUTCOME — the 3) arm (git-hooks/pre-commit:170-174) contains no exit, so exit 3 falls through exactly as a clean pass does (both exit 0, both let the commit land), and on the exit-STATUS channel they remain indistinguishable; accurate form is PARTLY REFUTED, distinguishable by message and not by exit status, and commit c96364db's FALSE ALARM wording is errata pointing here. (2) The parent card's SCOPE caveat (a source reading of 5.4.17, not a vendor statement; another version may differ) was dropped by this card and is RESTORED; the ubs:8875-8884 citation was read in the CLOSING turn, not in this turn, so it is INFERRED-INHERITED, not VERIFIED here. (3) 'governs exactly that arm and nothing else' was an uncited unit-of-analysis choice — --report-json is passed on the mktemp-SUCCESS path (git-hooks/pre-commit:91), a precondition ACROSS arms, not an arm; weakened to: the contract governs the invocation shapes that REQUEST a report, and the empty-report predicate sits inside the 0|1) arm. (4) The bare '10 measured states' figure, ENUMERATED: clean 0; warnings-only 0; critical 0 with findings printed; docs-only rc=3 to 0; empty index 0; ubs absent to 1; rc=2 to 1; rc=4 unknown to 1; report without totals to 1; mktemp failure to 0. (5) TERMINAL CONDITION, unstated before: no code change is owed and b72aff2a implements every arm correctly, so this card is COMPLETE when read and acknowledged by the owner; the errata is the deliverable, it is not a work item, and nothing should be pulled from it. (6) The exit-3 observations from the closing sequence exercised the one arm that runs no scan and are NOT end-to-end confirmation of the critical/advisory arms.
