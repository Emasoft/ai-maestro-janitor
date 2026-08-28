---
trdd-id: 3AKSYZRV
title: Duty 13 — split an ATOM that carries two topics, at any size
column: complete
created: 2026-08-28T07:52:50+0200
updated: 2026-08-28T10:05:00+0200
current-owner: janitor-session
task-type: feature
project-id: ai-maestro-janitor
parent-trdd: 87RKBYJ8
npt: []
eht: []
min-approval-requirement: none
---

# Duty 13 — split a multi-topic atom

Split out of **TRDD-87RKBYJ8** per its own rule: the remaining gap rows become their own cards, and
are never implemented under the parent id.

## What is missing

`atomize` ADDS markers to unmarked prose; it never SPLITS an atom that already exists. So an atom
carrying two distinct subjects stays one atom forever.

## The distinction that makes this its own card

**This is NOT the over-budget decomposition shipped under TRDD-VOWAUVE5.** That one triggers on
SIZE (`MEMGREP_ATOM_MAX_CHARS`, the "atom body is N chars (> 1500)" finding). This one triggers on
an atom holding TWO TOPICS **at any size** — a 400-char atom stating two unrelated facts is exactly
as unfindable as a 3000-char one, because `recall` ranks on the atom's single keyword set and a
two-topic atom's keywords necessarily serve neither topic well.

Do not implement this by lowering the size threshold. Size and topic-count are independent
properties and conflating them would make the size rule fire on well-formed long atoms.

## The hard part, stated so it is not discovered late

Deciding that an atom holds two topics is a JUDGEMENT, not a measurement — which is why this is an
agent duty and not a `lint` rule. A `lint` rule whose majority honest outcome is KEEP fires forever
and destroys the "gate and arbiter identical ⇒ the chore terminates" property (the reasoning
recorded on TRDD-JKJHV19B). Candidate ENUMERATION may be mechanical; the split decision is not.

## Acceptance

- [x] A candidate query that enumerates plausibly-multi-topic atoms without asserting they are
- [x] The split preserves BOTH topics' recall surfaces — neither inherits a keyword set tuned for the other
- [x] Lessons anchored to the original atom travel to the correct half, not to whichever is first
- [x] `uv run pytest -q`, ruff, mypy

## What shipped (2026-08-28)

Spec: **WM-CLI-21a** (re-tune both halves) and **WM-CLI-21b** (reassign the lesson anchors).

1. **Candidate query** — `memory_content_precheck.multi_topic_atom_candidates(root)`, surfaced as
   `memory_candidates_cli.py --intervention split-topic`, honouring a `"split-topic"` refusal
   ledger (page-granular, reusing the existing store).
2. **Recall surfaces** — `split-mem-atom --orig-keywords` / `--orig-desc`, held to the same
   floors as the new half's, applied to the original marker via `set_marker_field` (hoisted
   `pub(crate)` out of `mem_merge`).
3. **Lesson anchors** — the trailing `[^N]` run on the original's last body line now follows the
   ORIGINAL atom by default; `--lessons-to-new <LABELS>` assigns deliberately.

`pytest` 15899 passed / 0 failed; ruff + mypy clean; memgrep 250 unit + 146 integration.

**The advisor killed the original design and was right.** The first plan enumerated candidates by
building a graph over the atom's keyword phrases (edge = shared content word) and flagging ≥2
components. That is a false-positive machine: disjoint keyword clusters are the NORMAL shape of a
well-authored SINGLE-topic atom, because `keywords:` is deliberately a set of NON-synonymous
alternative phrasings a future searcher might arrive with. `consolidate_has_work` already records
the same finding for its own subject-overlap gate — the module knew, and I did not read it first.

**The floor was chosen by measurement, not by argument.** The advisor proposed the bare
splittability floor (≥2 body lines). Measured on this repo's PROJECT corpus: 159 atoms, **127**
pass that alone, **78** also have an internal paragraph break. The paragraph break roughly halves
the sweep and gives up nothing — both are structural, neither claims a subject count.

**The `[^N]` half was a latent corruption nobody had noticed.** `add-lesson` anchors to the atom's
LAST body line, which after a split is the SECOND half's last line — so every pre-existing lesson
mechanically went to the NEW atom, including ones whose `supersedes:` prop names the id the FIRST
half keeps. The card's phrasing ("not to whichever is first") had the direction backwards; the
real default was "whichever is last".

**Found only by running it:** with a paragraph break at the split point, a moved anchor landed
alone on the blank line. Fixed to target the last NON-blank line, with its own test. The unit
tests passed throughout — the end-to-end run on the installed binary is what caught it.

**Both `test_rules_installer` token-cap gates fired** on the SKILL.md edit (body 5880 > 5000,
description 237 > 200). Correct gate: the detail moved to `references/split-plan-details.md` and
the cap was left alone. That skill sits within ~20 tokens of the cap at HEAD, so ANY addition to
it now requires moving something out first — worth knowing before the next edit.

## DELIBERATELY NOT DONE — `split_has_work` is NOT wired to this candidate

The third source is built and callable but the scheduler gate is unchanged, so the topic split
only runs on a pass dispatched for another reason. Wiring it flips dispatch behaviour on every
machine at once, and the sweep it starts is long: at `split_per_day=4.5` and 78 candidates in ONE
scope, that is ~17 days of passes before the ledger retires them. The rate is bounded by the
scheduler (not by the candidate count), and it converts passes that today end "NOTHING DUE" into
judgement — so it is probably right. It should land as its own change, after the machinery has
been exercised, not as a side effect of introducing it.

**NEXT ACTION if picked up:** add `multi_topic_atom_candidates` as a third source in
`split_has_work` behind the same unchanged-corpus stamp the other gates use, and verify a
recorded refusal suppresses the next dispatch (the round-trip is already proven at the CLI level:
listed → refusal recorded → retired → page edited → revived).

## Notes and lessons learned
