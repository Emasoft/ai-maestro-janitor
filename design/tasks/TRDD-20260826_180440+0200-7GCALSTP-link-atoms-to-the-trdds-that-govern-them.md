---
trdd-id: 7GCALSTP
title: Link each atom to the TRDDs actually relevant to its content
column: backburner
created: 2026-08-26T18:04:40+0200
updated: 2026-08-26T18:04:40+0200
current-owner: janitor-main-session
task-type: feature
project-id: ai-maestro-janitor
scope: project
severity: minor
min-approval-requirement: none
labels: [wikimem, memgrep, memory-maintenance, provenance]
parent-trdd: 87RKBYJ8
npt: []
eht: []
implementation-commits: []
relevant-rules: []
---

# Duty 18 — ADD links to the TRDDs actually relevant to each atom

Split out of **TRDD-87RKBYJ8** per its own rule. Parent's priority: after 16-17, 14, 13.

**The duty, verbatim:** ADD links to the **TRDDs actually relevant** to each atom's content.

## Why this is the provenance half of the memory system

The commit-discipline rule names the chain this duty completes: `memory.commits:` →
`memory.trdd:` → `implementation-commits:` → `git show <sha>`. That chain is what lets a memory
maintainer demote an obsolete fact to a dated lesson **without inventing the reason** — it sources
the WHY from the change that caused it. An atom with no TRDD link dead-ends that chain, which
makes the fact un-prunable rather than merely unexplained.

## ⚠ Do NOT script this from a grep — the failure is already measured

TRDD-3UX67NT5 tested exactly this shape on the TRDD side and found it produces FALSE POSITIVES: a
commit whose BODY mentions a card while its SUBJECT implements a different one matches a naive
grep. The same hazard applies in reverse here — an atom mentioning a card id is not necessarily
governed by it.

**A wrong pointer here is worse than an absent one**: an absent link makes someone go looking, a
wrong link stops them looking. So candidate proposal may be automated; the link itself needs the
same per-item confirmation 3UX67NT5 demands.

## Acceptance

- [ ] Candidates proposed from atom content, with the evidence for each proposed TRDD
- [ ] Each link confirmed per atom before it is written — never bulk-applied from a grep
- [ ] A test proving a body-only mention does NOT become a link (the 3UX67NT5 false-positive class)
- [ ] Links are bidirectional where the target is a wikimem page (the LINK LAW); a TRDD is an
      external ref and does not require a back-link
- [ ] `uv run pytest -q`, `ruff check scripts tests`, `mypy scripts/ --ignore-missing-imports`
