---
trdd-id: QDYQLM5V
title: Move an off-topic atom to the page that owns its topic
column: backburner
created: 2026-08-26T18:04:40+0200
updated: 2026-08-26T20:03:23+0200
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

# Duty 14 — detect an OFF-TOPIC atom and MOVE it to the right page

Split out of **TRDD-87RKBYJ8** per its own rule (remaining gap rows become their own cards; never
implemented under the parent id). Parent's priority: after 16-17 (TRDD-JKJHV19B).

**The duty, verbatim:** detect an OFF-TOPIC atom and MOVE it to the wikimem page right for its
topic (e.g. methodological considerations → the best-practices page).

## Why it matters, in the parent's own words

The ROOT PRINCIPLE the parent records from the USER: *a wikimem page exists ONLY to collect the
atoms about the SAME topic, so every page must be a single, distinct topic.* Duty 14 is one of the
three consequences (with 10 merge and 15 create). Topic, not title string, decides identity.

The standing rule states the same thing operationally: a case page holds CASE facts; a
transferable way of WORKING belongs on the methodology page that owns it. A general lesson parked
in a case page pollutes that page AND scatters the methodology.

## ⚠ The move must be a RELOCATION, never a deletion

"Never delete knowledge — relocate it." A moved lesson leaves a `[[link]]`, not a hole. So this
pass is two writes (source loses the atom, gains a link; target gains the atom) and the verifier
must prove the atom survives byte-for-byte across BOTH pages — a shape `verify_repair` does not
cover today, since it proves one write at one path.

**That is the real work of this card:** a two-page atomic move with a verifier that proves
conservation across the pair. Everything else is candidate selection.

## Observed instance to use as the first fixture

2026-08-26: `"compose all three roots"` — a general recall rule — lived only on a case page
(`external-claude-session-is-not-an-ai-maestro-agent`), which a peer correctly called a placement
defect. It was resolved by a back-link rather than a move, deliberately, because the general form
had by then been written onto the methodology page. That is duty 14's decision in miniature: MOVE,
or LINK and leave. Both are legitimate and the pass must be able to choose.

### A SECOND instance, found 2026-08-26 19:55 — and this one wants a MOVE, not a link

`ATOM-BLKL-TEST` on `.claude/project/memory/janitor-daemon-bulk-lane.md:40`. The page is about
the daemon's bulk lane; the lesson is about **test isolation** — *"DO NOT assume a monkeypatched
`CLAUDE_PROJECT_DIR` isolates janitor state in tests, BECAUSE `state.project_root`/`janitor_root`/
`state_dir`/`log_dir` are lru-cached process-wide"*. Nothing about it is true only of the bulk
lane; it would be equally true of any janitor test, which is this duty's own test for off-topic.

**And the destination already exists**: `janitor-keepalive-test-isolation-fsevents`, whose
description is literally *"a unit test wrote to the REAL ~/.claude/janitor-global-state or the
real plugin DATA dir"* — the same subject. So unlike the first fixture, the general form has NOT
already been written elsewhere, which is exactly what made LINK the right call there and makes
MOVE the right call here. **Two instances, opposite verdicts, same duty** — which is the pair
this card needs, because a pass validated on one of them alone would hard-code the wrong default.

How it was found is worth keeping too: it surfaced as a `lesson-uncited` INFO in a routine
`memgrep lint` run, buried among 71 findings of which the other 70 were non-defects. The
retrieval-engine page now carries the measured triage (`ATOM-TLL1-PZOJ`); the point for THIS card
is that duty-14 defects do not announce themselves as duty-14 defects — this one arrived
disguised as a footnote-citation nit.

## Acceptance

- [ ] A candidate query proposing (atom, current page, better page) triples with the topic
      evidence for each
- [ ] A two-page atomic move through the transaction core, with a verifier proving the atom's
      body and lessons survive byte-for-byte and the source retains a `[[link]]`
- [ ] LINK-INSTEAD-OF-MOVE is an expressible outcome, not a failure to move
- [ ] A test drives an atom that is off-topic for its page and on-topic for another, asserts the
      move, and asserts a crash mid-move leaves BOTH pages intact (the transaction core's job,
      proven here for the pair case)
- [ ] `uv run pytest -q`, `ruff check scripts tests`, `mypy scripts/ --ignore-missing-imports`
