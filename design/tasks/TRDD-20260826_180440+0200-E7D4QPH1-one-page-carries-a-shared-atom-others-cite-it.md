---
trdd-id: E7D4QPH1
title: When two pages need the same atom only one carries it and the other cites it
column: backburner
created: 2026-08-26T18:04:40+0200
updated: 2026-08-26T18:04:40+0200
current-owner: janitor-main-session
task-type: feature
project-id: ai-maestro-janitor
scope: project
severity: major
min-approval-requirement: none
labels: [wikimem, memgrep, memory-maintenance, consolidate]
parent-trdd: 87RKBYJ8
npt: []
eht: []
implementation-commits: []
relevant-rules: []
---

# Duty 11 — search + merge same-content atoms; ONE page carries, the others CITE

Split out of **TRDD-87RKBYJ8** per its own rule.

**The duty, verbatim:** Search + merge atoms with the **same content**, avoiding duplicates. If two
topic pages both need the same atom, only **ONE page carries it**; the other CITES it with a
titled hyperlink (an informative title, not too long).

## The failure this prevents, measured twice on 2026-08-26

Both instances came from a pre-write recall over too few scope roots:

- A peer authored a PROJECT-scope duplicate of a page that already had a canonical USER-scope
  home, same day, discovered only when a later probe happened to include the USER root.
- The same session ran three pre-write recalls one scope at a time; they happened not to
  duplicate anything, which is luck rather than method.

**Duplicate atoms are worse than a missing one** because recall then splits its ranking between
two copies and the reader cannot tell which is current — and a correction applied to one copy
silently leaves the other asserting the old fact.

## ⚠ The dedup key is CONTENT, not text

Two atoms saying the same thing in different words are one duplicate; two atoms sharing a
paragraph but making different claims are not. A textual similarity threshold gets both wrong,
which is why the parent assigns this to the consolidate chore's agent rather than to a lint rule.

## Acceptance

- [ ] Candidate pairs proposed with the shared CLAIM identified, not merely a similarity score
- [ ] The carrying page is chosen by topic ownership (which page is the atom ON-topic for), and
      the other gets a titled citation link — informative, and short
- [ ] Both ends wired in the same edit (the LINK LAW)
- [ ] The surviving atom keeps its original id; the citation names it so a reader lands on the
      atom, not merely on the page
- [ ] A test drives two pages carrying the same claim in different words, asserts one carrier and
      one citation, and asserts a later correction to the carrier is visible from the citing page
- [ ] `uv run pytest -q`, `ruff check scripts tests`, `mypy scripts/ --ignore-missing-imports`
