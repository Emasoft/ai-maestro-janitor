---
trdd-id: 3UX67NT5
title: implementation-commits is empty or missing on most cards that have shipped code
column: backburner
created: 2026-08-26T08:32:00+0200
updated: 2026-08-26T18:35:00+0200
current-owner: janitor-main-session
task-type: docs
project-id: ai-maestro-janitor
scope: project
severity: minor
min-approval-requirement: none
labels: [board, provenance, backtracking]
npt: []
eht: []
implementation-commits: []
relevant-rules: []
---

# The backtracking chain is broken on most cards

`implementation-commits:` is the field that answers *"a bug surfaced today — which TRDD
introduced the code that caused it?"* It is the only structured link from a commit back to the
decision behind it, and the TRDD rules name it exactly that: the backtracking field.

## Measured 2026-08-26

Swept every NON-terminal card (`todo`/`blocked`/`backburner`/`planned`) for an empty or absent
`implementation-commits:` while commits citing that card's id exist. **12+ cards**, including
`1QJIZFFW` (6 candidate commits), `WP7TCRME` (4), `87RKBYJ8` (3), `88ZVEQY7` (3), `GZXTSJSR` (2),
`5RXBI65T` (2). One case was fixed by hand while it was in front of me — `9T0U3M00`, filled with
`0a009277`, `ed4242f0`.

Terminal cards were deliberately NOT swept: they are frozen by the TRDD rules, and this is not
one of the narrow exceptions.

## ⛔ DO NOT FIX THIS WITH A SCRIPT — the obvious automation is measurably wrong

The tempting fix is `git log --grep=<id>` per card, write the SHAs. **Tested on `1QJIZFFW` and it
produces false positives**: `c23e9e49 fix(trdd-drift): … (TRDD-FDV1RQEB)` matches a `1QJIZFFW`
grep because the commit BODY mentions that card while its subject implements a DIFFERENT one.
Two further matches cite the id nowhere in their subject.

So a scripted fill would write commits that did not implement the card into the one field whose
entire purpose is answering "which change caused this". A wrong pointer here is worse than an
absent one: an absent field makes someone go looking, a wrong field stops them looking. This is
the kanban rule's "do not mass-repair a stalled board with a script" in its exact form.

**The distinguishing signal is the SUBJECT, not the message.** Commit discipline puts the
governing `TRDD-<id8>` in the commit SUBJECT; a body mention is a cross-reference. So the
candidate set is `git log --format='%h %s' | grep '<id>'` — subject only — and even that needs a
human to confirm the commit implements rather than merely cites.

## The upstream cause worth fixing instead

Cards are getting their code shipped without the field being updated in the same edit. Filling
12 cards retroactively is worth little if the 13th is authored the same way tomorrow. The
durable fix is at the moment of the commit, not in a later sweep — the `commit-discipline` rule
already requires the id in the subject, which is what makes recovery possible at all.

## ⏵ 2026-08-26 18:20 — SIX CARDS FILLED, per-card, by reading each commit rather than grepping

The six named in the sweep above are done. Method exactly as this card demands — SUBJECT-matched
candidates, then a human read of each before writing it:

| card | filled | candidates rejected |
|---|---|---|
| 1QJIZFFW | `df7d4cb3, 169d967d, 295c1243` | 8 docs commits (STATE edits, column moves, policy verdicts) |
| WP7TCRME | `b8dbc254, 7ad7c0ee, da249936, d4d9f726` | 6 docs commits |
| 87RKBYJ8 | `3179af38` | 7 docs commits |
| 5RXBI65T | `0581b940` | 9 docs commits — this card is mostly a whodunit, so its history is nearly all reasoning |
| 88ZVEQY7 | `cda30a23` | 2 (one card-creation, one a shared CLAUDE.md map refresh citing two cards) |
| GZXTSJSR | `cf9fb7a1` | 1 card-creation |

**The discriminator that did the work is `feat(`/`fix(` vs `docs(`** — this field is the
backtracking chain from a BUG to the change that caused it, so a commit that edited the card's
own prose can never answer it. 33 of the 39 subject-matched commits were docs. That ratio is
itself the finding: subject-matching alone would have written mostly noise into the one field
whose value is precision.

**One case needed more than the subject, and it is the one this card warned about.**
`3179af38 feat(memory): sync subconscious procedures … (AP2X9A0H b, NM4TPCQ9 prong 2, 87RKBYJ8
gap list)` cites THREE cards in one subject. Reading its file list settled it — it touched
`skills/janitor-memory-{atomize,consolidate,harvest}/SKILL.md`, which are exactly the artifacts
87RKBYJ8 governs ("make the existing ones enforce these rules"). Kept. A subject-only rule would
have had to guess, and a body-grep would have taken all three.

### The sweep RE-RUN, and "12+" was wrong in both directions

Enumerated rather than counted: **28** non-terminal cards have an empty field AND at least one
subject-matched commit — more than "12+". But filtering to commits that are actually CODE
(`feat|fix|perf|refactor`) leaves **7**, because the other 21 match only `docs(` commits, which
this field must never hold.

So the real backlog was never 12. It was 6 already done, plus these 7 — and 21 cards that
correctly have an empty field and should be left alone. **A sweep that counts subject matches
overstates the work by 3x; the code-commit filter is what makes the number mean something.**

| card | filled |
|---|---|
| 7NSRD8OV | 16 SHAs — a genuinely heavily-worked card (`fix(TRDD-7NSRD8OV): …` throughout) |
| 6WM4BFKF | `e607e95a` |
| 9ZPU69UC | `1d5a3b16` |
| HC7CQT10 | `4515ca18` |
| 6054NY8H | `2d30dd7b` |
| 79LXF6PJ | `155833b3` |
| **JPL0JU86** | **NONE — candidate REJECTED** |

**The rejection is the one worth reading.** `7b2c64eb feat(board): shipped-unreleased rung +
JPL0JU86's fix is undone by a live mechanism` is a `feat(` commit naming JPL0JU86 in its SUBJECT
— so it survives every filter this card recommends. Its file list refutes it: it touched
`scripts/detectors/trdd-state-reconciliation.py`, `scripts/lib/trdd_common.py` and their tests,
i.e. board machinery, and it merely REPORTS that JPL0JU86's fix was undone. Writing it in would
have pointed the backtracking chain at code that has nothing to do with the card's subject.

**That closes the loop on this card's own thesis.** Subject-matching is necessary and not
sufficient; the file list is the arbiter, and only for the handful the filters let through.

**Remaining:** the 21 docs-only cards need no action. This card can go terminal once someone
confirms that reading.

## Acceptance

- [ ] Each swept card's field filled from SUBJECT-matched commits, confirmed per card by a human
      or an agent that read the diff — never from a body grep
- [ ] A check that flags a card whose column has reached `complete` with an empty
      `implementation-commits:` while subject-matched commits exist
- [ ] The check does NOT auto-fill; it reports, because of the false-positive class above

## Notes and lessons learned

Found via TRDD-9T0U3M00, whose field was empty while its fix had shipped AND been tested. The
sweep was the derived task from that one card; the false-positive discovery came from verifying
the automation before trusting it, which is the only reason this card says "do not script it"
instead of shipping a broken script.
