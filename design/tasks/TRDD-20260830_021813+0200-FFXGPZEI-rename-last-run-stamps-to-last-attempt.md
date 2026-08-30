---
trdd-id: FFXGPZEI
title: rename last-run stamps to last-attempt so the wrong inference cannot be spelled
column: backburner
created: 2026-08-30T02:18:14+0200
updated: 2026-08-30T02:18:14+0200
current-owner: janitor-main-session
task-type: refactor
scope: project
project-id: ai-maestro-janitor
severity: low
min-approval-requirement: none
blocked-by: []
npt: []
eht: []
relevant-rules: []
external-refs: [TRDD-H8WRCW0I]
---

# `last-run-*.ts` invites the one inference it cannot support

## The proposal (peer suggestion, AMAMA 2026-08-30)

`.janitor/state/last-run-<detector>.ts` records **when a pass was attempted**. It does not record
whether that pass did anything: `dispatch.py:2159` writes it unconditionally after the subprocess
returns, so a detector that declined at its first gate stamps exactly like one that completed.

A reader looking for "is this detector healthy?" finds a field called `last-run`, sees a fresh
timestamp, and concludes it ran. That inference is wrong and the field name invites it.

The peer's argument for renaming to `last-attempt-*.ts`: **it makes the wrong inference impossible
to spell**, whereas the note now sitting in TRDD-H8WRCW0I only protects readers who read that
card. Two sessions spent most of an investigation on exactly this confusion on 2026-08-29/30 —
78 imaginary days of a "dark lane" that turned out to be an abandoned state dir, and separately a
"the guard ran 40 minutes ago" that was a decline at gate 3.

## Why this is `backburner` and not `todo`

The rename is cheap to write and expensive to land, and the cost is not in the code:

- **Every stamp resets.** Renaming the file means every detector reads `0` for its last run and
  becomes immediately due, so the next heartbeat on every project on the machine fires *all* of
  them at once. That is a thundering herd against `gh`, the network, and the model, on a host
  whose whole point is staying quiet.
- **A migration that renames in place** (read old, write new, delete old) avoids the herd but is
  itself state-mutating code running on every project — the class of change most likely to leave
  a host in a half-migrated state if it is interrupted.
- **The fleet is not only this repo.** Other plugins and the ai-maestro server read these names;
  `grep -rn "last-run-" --include=*.py --include=*.md` is the starting point but crosses repo
  boundaries, and a rename that lands here first breaks whoever reads them there.

So the decision needed first is not "is the name better" (it is) but **"is the name worth a
fleet-wide state migration"**, and that is a judgement about disruption, not about clarity.

## A cheaper alternative worth pricing first

Leave the filename and add a sibling that answers the question the reader actually has:
`last-outcome-<detector>.ts` carrying `applied` / `declined:<reason>` / `error`. Additive, no
migration, no herd, and it makes "did it work" answerable without making "when was it attempted"
lie. The rename would still be nicer; this is what to do if the migration is judged too costly.

## Acceptance

- [ ] a decision recorded: rename, add a sibling outcome stamp, or neither — with the reasoning
- [ ] if renaming: a migration that cannot thunder (rename in place, never reset to 0) and is
      idempotent under interruption
- [ ] if renaming: every reader across the fleet is found first, including outside this repo,
      and the cross-repo ones are coordinated before the rename lands here
- [ ] `uv run pytest -q` + `ruff check scripts tests` + `mypy scripts/ --ignore-missing-imports`

## Notes and lessons learned

- **Do NOT rename and let the stamps reset.** The disruption would be silent, machine-wide, and
  exactly the kind of self-inflicted noise that makes a user disarm the janitor.
- The underlying lesson is already recorded on TRDD-H8WRCW0I and does not depend on this card
  landing: **`last-run-*.ts` answers "when was this last attempted", never "did it work".**
  This card is about making that unnecessary to know, not about establishing it.
