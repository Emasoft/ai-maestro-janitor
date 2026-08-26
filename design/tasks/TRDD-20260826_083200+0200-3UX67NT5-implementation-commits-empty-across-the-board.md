---
trdd-id: 3UX67NT5
title: implementation-commits is empty or missing on most cards that have shipped code
column: backburner
created: 2026-08-26T08:32:00+0200
updated: 2026-08-26T08:32:00+0200
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
