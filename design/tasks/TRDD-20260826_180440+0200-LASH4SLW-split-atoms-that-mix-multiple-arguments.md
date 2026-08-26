---
trdd-id: LASH4SLW
title: Split an atom that mixes multiple arguments into one-fact atoms
column: backburner
created: 2026-08-26T18:04:40+0200
updated: 2026-08-26T18:04:40+0200
current-owner: janitor-main-session
task-type: feature
project-id: ai-maestro-janitor
scope: project
severity: major
min-approval-requirement: none
labels: [wikimem, memgrep, memory-maintenance, atomize]
parent-trdd: 87RKBYJ8
npt: []
eht: []
implementation-commits: []
relevant-rules: []
---

# Duty 13 — SPLIT atoms that mix multiple arguments

Split out of **TRDD-87RKBYJ8** per its own rule. Parent's priority: after 16-17 and 14.

**The duty, verbatim:** SPLIT atoms that mix multiple arguments (especially different topics) —
keep atoms ATOMIC and easy to grep by keywords: **one paragraph / one table / one list per atom**.

## The measured case that shows why this is not cosmetic

2026-08-26, on this machine. A peer authored one atom covering two failure modes — asking a
corpus a question with the wrong QUESTION (one identifier) and with the wrong POPULATION (one
scope root of three). `memgrep lint` flagged it only as `atom-oversized` (1529 chars > 1500),
which is the weakest possible signal for what was actually wrong.

**The atom's own thesis was "these are not the same error", stored as one atom — its structure
contradicted its content.** After the split (`ATOM-7LCN-GJ2J` / `ATOM-W99A-N60G`), each symptom
got a precise first-rank hit; before it, one atom answered both queries and neither answered well.

That is the argument for this duty in one case: a mixed atom degrades RECALL, not just tidiness,
because keywords for two subjects on one atom make it rank mediocre for both.

## ⚠ The split must not be driven by the size lint

`atom-oversized` is a proxy and a poor one. A long single-subject atom is fine; a short atom
mixing two subjects is the real defect and is INVISIBLE to a character count. A pass keyed on
size would split the wrong atoms and miss the right ones.

The honest signal is the atom's own keyword set: two disjoint symptom clusters on one atom is the
tell. That is a semantic judgment, which is why this is an agent chore and not a lint rule.

## Acceptance

- [ ] Candidate selection keys on DISJOINT KEYWORD CLUSTERS, not on length — with a test proving a
      short mixed atom is a candidate and a long single-subject atom is not
- [ ] Each resulting atom carries its own keywords and its own id; the original id is preserved on
      the half that keeps the original subject (never renumbered into two new ids)
- [ ] Recall proof per split: each half ranks FIRST for its own symptom and does not rank for the
      other's — the measurable definition of a successful split
- [ ] Every edit through the transaction core; no lesson or fact lost
- [ ] `uv run pytest -q`, `ruff check scripts tests`, `mypy scripts/ --ignore-missing-imports`
