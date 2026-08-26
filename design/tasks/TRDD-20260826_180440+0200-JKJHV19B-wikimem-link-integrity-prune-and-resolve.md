---
trdd-id: JKJHV19B
title: Wikimem link integrity — prune stale and duplicate links, resolve dangling ones
column: todo
created: 2026-08-26T18:04:40+0200
updated: 2026-08-26T19:00:00+0200
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

## ⏵ 2026-08-26 19:00 — CANDIDATE QUERY BUILT AND RUN; 10 defects FIXED; the rest is judgment

Acceptance box 1 is done, and it produced a taxonomy rather than a list — which is the point,
because a flat "98 dangling links" would have been 73% noise.

**Raw query over all three scope roots: 262 pages, 884 resolving page links, 98 non-resolving.**
Classified:

| class | n | verdict |
|---|---|---|
| 1 · PROSE *about* links — `[[wikilink]]`, `[[link]]`, `[[links]]` | **72** | NOT defects. Pages discussing the wiki syntax, e.g. "wire both ends of a `[[wikilink]]`" |
| 2 · `.md` extension, target exists (`[[foo.md]]` vs page `foo`) | **9** | mechanical — **FIXED** |
| 3 · separator mismatch (`-` vs `_`), target exists | **1** | mechanical — **FIXED** |
| 4 · genuinely missing subject | **19** refs / 12 names | the judgment call this card is for |

**Class 1 is the finding that matters for the eventual implementation.** Three quarters of a
naive dangling-link report is prose that merely spells a wikilink. A pass that "resolves dangling
links" without this filter would have rewritten or deleted 72 pieces of correct writing — and it
would have looked like it was doing its job. The candidate query MUST exclude prose-mention
targets, and the exclusion list is short and stable (`wikilink(s)`, `wikilinked`, `link(s)`,
`wikimem`, `name`, `page`).

**Classes 2 and 3 are fixed** — 10 links, each provably safe because the target page exists under
a trivially different spelling. Done through `memgrep edit --replace-all` per page; LOCAL scope
now lints 0, USER 2 (pre-existing `atom-oversized`, unrelated).

**Class 4 — the 12 distinct missing subjects, for whoever implements the pass:**
`who-verifies-and-closes-work` · `project-ai-maestro-janitor-oauth-rotator` ·
`reference_memory_system_integration` · `universal-plugins-ignore-aimaestro-instruction-set` ·
`what-ai-maestro-is` · `security-act-dont-ask` · `removal-blast-radius` ·
`agent-claims-the-api-was-never-delivered` · `claim-verification` ·
`governance-ssot-is-the-governance-rules-branch` · plus `B` and `Note`, which are junk from a
table or template and are the only two that should simply be PRUNED.

Ten of these are exactly the deliberate forward-references the protocol sanctions ("a `[[name]]`
that doesn't match yet marks something worth writing later"), so KEEP is the likely verdict for
most — which is why this card demands KEEP be expressible.

### A duplicate page found while fixing, worth its own attention

`feedback_memory_dual_test_evaluation.md` exists in **BOTH** LOCAL and USER scope with different
content — a genuine cross-scope duplicate, i.e. duty 10/11 territory (TRDD-E7D4QPH1). Found only
because the fix failed on the USER copy and succeeded on the LOCAL one. Not touched here beyond
the link fix; recorded so E7D4QPH1 starts with a real instance instead of a hypothetical.

## Acceptance

- [x] A candidate query that lists, per page: duplicated links, links to non-existent pages, and
      links whose target exists but no longer covers the subject. **Built and run** — see the
      taxonomy above; the load-bearing part is excluding prose-mention targets (72 of 98)
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
