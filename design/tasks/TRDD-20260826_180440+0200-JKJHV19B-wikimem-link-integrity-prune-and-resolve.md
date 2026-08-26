---
trdd-id: JKJHV19B
title: Wikimem link integrity — prune stale and duplicate links, resolve dangling ones
column: todo
created: 2026-08-26T18:04:40+0200
updated: 2026-08-26T18:04:40+0200
current-owner: janitor-main-session
task-type: feature
project-id: ai-maestro-janitor
scope: project
severity: major
min-approval-requirement: none
labels: [wikimem, memgrep, memory-maintenance, links]
parent-trdd: 87RKBYJ8
npt: []
eht: []
implementation-commits: []
relevant-rules: []
---

# Duties 16-17 — link integrity in the wikimem editor

Split out of **TRDD-87RKBYJ8** (the spec + reconciliation ledger) per its own rule: the remaining
gap rows become their own cards when their turn comes, and are never implemented under the parent
id. **This is the next increment** — the parent's audit put 16-17 immediately after the four
already-terminal children (57WJL5L2, AZ6QRK0D, J3ZH3RSI, 3SOO1RWE).

## The two duties, verbatim from the parent

16. EDIT / POLISH the references + links to other wikimem pages and atoms; PRUNE the ones that are
    duplicated or point to outdated pages that no longer exist.
17. If a link/hyperlink is DANGLING (no corresponding page or atom), CREATE the missing page or
    atom.

## Why these two are ONE card and not two

They are the two halves of one decision made per link. Reaching a dangling `[[link]]`, the pass
must choose between PRUNE (16) and CREATE (17), and the choice needs the same evidence in both
cases — what the link was reaching for, whether any other page already covers it, whether the
target was renamed or genuinely never existed. Splitting them would put the two outcomes of a
single judgment in different cards and guarantee that one of them is implemented without the
other, leaving a pass that can only ever delete or only ever create.

## ⚠ The hazard that makes this NOT a mechanical sweep

**A dangling link is not automatically a defect.** The memory protocol says so explicitly: a
`[[name]]` that does not match an existing memory *"is fine — it marks something worth writing
later, not an error"*. So a pass that resolves every dangling link by deletion destroys exactly
the forward-references the protocol asks authors to leave, and a pass that resolves them all by
creation manufactures empty pages nobody wrote.

That is the whole design problem of this card, and it is why the parent deferred it rather than
scripting it. The distinguishing evidence is not in the link — it is in whether the SUBJECT the
link names is one the corpus should hold.

## What already exists (verify before building — the parent's own lesson)

- `memgrep lint` already reports `link-one-sided` (measured today: it flagged a real one-sided
  link within minutes of a peer's write, and the LINK LAW fix was a one-line back-link).
- `memgrep links --to / --from` exists; note `reference_memgrep_links_to_from_semantics` records
  that its direction reads inverted to newcomers.
- The transaction core (`memory_txn` / `memory_edit_verify`) already proves no knowledge is lost,
  and `verify_repair` is the right verifier shape — an edit here is one write at the page's own
  path, exactly like a repair.

So the missing piece is the DECISION procedure and its candidate query, not the machinery.

## Acceptance

- [ ] A candidate query that lists, per page: duplicated links, links to non-existent pages, and
      links whose target exists but no longer covers the subject
- [ ] The PRUNE/CREATE decision is made per link with a recorded reason, and a deliberate
      forward-reference is a THIRD outcome (KEEP) — a pass that cannot express KEEP is wrong by
      construction
- [ ] Every edit goes through the transaction core; `verify_repair` proves no lesson or atom is
      lost
- [ ] A test drives a page carrying one duplicate link, one dangling forward-reference, and one
      link to a deleted page, and asserts exactly one prune, one keep, one create/repair — the
      three outcomes must be distinguishable or the pass has no decision in it
- [ ] `uv run pytest -q`, `ruff check scripts tests`, `mypy scripts/ --ignore-missing-imports`

## Notes and lessons learned

The LINK LAW ("every link is bidirectional — wire both ends in the same edit") is the standing
rule this duty enforces retroactively. Measured 2026-08-26: a peer agent that had that rule in its
own loaded context still wired one end, and `memgrep lint` caught it — evidence that the automated
half is the reliable half here, and the reason this card should lean on lint's finding set rather
than on a fresh scanner.
