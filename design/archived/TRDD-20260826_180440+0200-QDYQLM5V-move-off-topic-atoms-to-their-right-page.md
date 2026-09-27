---
trdd-id: QDYQLM5V
title: Move an off-topic atom to the page that owns its topic
column: complete
created: 2026-08-26T18:04:40+0200
updated: 2026-09-27T11:37:11+0200
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
status: archived
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

- [x] A candidate query proposing (atom, current page, better page) triples with the topic
      evidence for each
- [x] A two-page atomic move through the transaction core, with a verifier proving the atom's
      body and lessons survive byte-for-byte and the source retains a `[[link]]`
- [x] LINK-INSTEAD-OF-MOVE is an expressible outcome, not a failure to move
- [x] A test drives an atom that is off-topic for its page and on-topic for another, asserts the
      move, and asserts a crash mid-move leaves BOTH pages intact (the transaction core's job,
      proven here for the pair case)
- [x] `uv run pytest -q`, `ruff check scripts tests`, `mypy scripts/ --ignore-missing-imports`

## Approval log

- 2026-09-26T13:23:24+0200 — column → dev by main-agent@ai-maestro-janitor. Machinery audit 2026-09-26: boxes 2-3 (two-page atomic move + LINK-instead-of-MOVE) already met by memgrep migrate-mem-atom with 12 Rust tests (159/0 suite green) — those boxes tick on evidence. Remaining: box 1 (candidate query) + box 4 (off-topic detection test) = a scheduler-level 'relocate' chore wired through memory_settings.INTERVENTIONS, memory-maintenance._MARKERS, content_has_work/migrate_has_work, memory_candidates_cli, the heartbeat-protocol rule, and the skill. Owner keep-going directive drives the pull.
- 2026-09-26T21:09:57+0200 — column → testing. all acceptance boxes met: box1 wiring+skill committed 5a9d19c4+29474310, box2-3 migrate verb, box4 scenario test 2a8380b0; gates green; 4 review rounds processed
- 2026-09-27T11:37:11+0200 — COMPLETE by user. owner batch acceptance 2026-09-27 (verbatim directive: 'delegate to many lean-worker agents each pending task. complete all TRDDs.'): code shipped in 3.6.3, gates green, evidence current.

## STATE

Box 1 wiring landed 2026-09-26 pm: heartbeat rule row + _ALL_MARKERS pin + selftest list + janitor-memory-relocate skill (MOVE-vs-LINK decision rule per review blocker; STATE_DIR consume-don't-resolve) + agent skills list + guard-test 9-chore fixture + new cross-check test (detector _MARKERS must appear in rule/selftest/agent — enforced, not remembered). Review fork verdict: commit stands; its 3-shapes contract-test claim REFUTED vs memory.rs:6644-6656 (two message arms, both already pinned at :10814/:10836). Gates green pre-edit (17559/2); post-edit gates running.
Full suite AT HEAD verified 2026-09-26 (the review's box-5 remediation): 17561 passed, 2 skipped, 8 subtests, exit 0 in 600.6s — the tick now cites current evidence, not the pre-wiring run. No further column move this turn per the review; ai_review awaits the board's pull.
Box-5 stamp provenance settled (review round 6 remediation): the +2 vs the 17559 baseline are (1) tests/test_heartbeat_protocol_rule.py::test_rule_covers_every_detector_memory_marker (5a9d19c4) and (2) the parametrized tests/test_skill_frontmatter_yaml.py instance for the new janitor-memory-relocate skill dir — verified by diffing collected ids against a throwaway clone of 2a8380b0 (17561 → 17563). The 17561-run was concurrent with the split-chore agent; its blast radius is the live memory corpora only, which no repo-pinned suite test reads — nothing flaked and the pass count is exact.
Round-7 remediations (all one-clause): (1) blast-radius hedge — the no-repo-pinned-test-reads-the-corpora claim is as far as session knowledge goes, and the janitor-keepalive-test-isolation-fsevents incident is the precedent for why this class of claim carries a hedge; (2) count disambiguation — 17561/17563 above are COLLECT counts; a run's PASSED count is collect minus the 2 skips (HEAD: 17563 collected − 2 skipped = 17561 passed; baseline: 17561 − 2 = 17559 — two independent chains closing is corroboration); (3) mechanism — the frontmatter test auto-enumerates skills/*/SKILL.md, so the new skill dir FORCES exactly one added instance; the +1 is mechanical, not coincidental.
Round-8 scoping fix for the disambiguation clause: read the round-6 line's 17561/17563 as COLLECT counts (the collected-ids diff context); the round-5 line's 17561 is the RUN's PASSED count — the two coincide numerically by the arithmetic (17563 collected − 2 skipped = 17561 passed), which coincidence is the trap the clause guards against, not a contradiction between the lines.
