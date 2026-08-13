---
trdd-id: XOITBRIZ
title: The code-fence mask hides dynamic-exec-in-body's primary threat — the fence is not the signal, the surrounding prose is
column: testing
created: 2026-08-13T11:26:39+0200
updated: 2026-08-13T12:20:00+0200
current-owner: janitor-main-session
task-type: security
approval-tier: 0
scope: project
severity: high
relevant-rules: []
npt: []
eht: []
external-refs: [janitor#226, janitor#254, TRDD-HYV0SOC6]
---

# `dynamic-exec-in-body` catches 1 of 3 of its own documented shape, because the mask is aimed at the wrong feature

## The mask, and why it exists

`agent_config_patterns.scan_text` masks markdown code fences before running
`dynamic-exec-in-body` on prose (FP-hardening round 3). Its stated rationale, verbatim from the
code: *"an `eval()` inside a documentation code fence is INERT (the downstream LLM doesn't execute
fenced code)."*

That is true of a README. **It is false of a SKILL.md**, where a fenced block is precisely the
thing the agent is instructed to run — the janitor's own skills are written that way
(`/janitor-arm` step 1 is a fenced `uv run …` the agent executes). So the mask blinds the rule in
exactly the file type the rule exists for.

## Measured, three ways — and the first measurement was WRONG

> **⚠ SUPERSEDED NUMBERS BELOW — kept because the reasoning is still correct, but do NOT quote the
> `3/3`.** Every figure in this section was measured on a 3-sample attack class that the fix was
> tuned against. The blind set later put the same rule at **6/9**, and the old mask at **3/9** on
> that same set. The Acceptance section carries the current, like-for-like numbers; this section is
> the argument, not the score.

| mode | recall | FP on security-docs | FP on the 68 existing benign |
|---|---|---|---|
| **masked (shipped)** | 1/3 | 0/4 | 0/68 |
| unmasked | 3/3 | **4/4** | 0/68 |
| **negative-context** | **3/3** | **0/4** | **0/68** |

**The first run said "unmasking is free" — 3/3 recall, 0 false positives — and that was an
artifact, not a result.** ZERO of the 68 benign samples contain any exec-shaped token at all, so
the population could not observe the false positive the mask was built to prevent. It is the same
trap as the base64 floor in TRDD-HYV0SOC6's sibling fix an hour earlier: a rule scored against a
population that never asks the question comes back clean and means nothing. The `security-docs`
column above is a NEWLY AUTHORED population (a scanner SKILL.md listing eval/exec as detection
targets, a review skill quoting `shell=True` as an anti-pattern, a linter doc for a banned
`os.system`, an incident write-up quoting the attacker's payload) — with it present, unmasking
costs 4/4. So the mask IS load-bearing and must not simply be removed.

## The fix: the fence is not the signal, the PROSE AROUND IT is

A security doc says *report / reject / ban / we removed this*. An attack says *apply / evaluate /
run this*. Run the rule UNMASKED and drop matches whose surrounding ±400 chars name the code as
something to find or avoid. This is not a new idea in this module — `exfil-webhook-sink` already
does exactly this via `has_ioc_context_near`.

Prototyped and measured: **3/3 recall, 0/4 security-docs FP, 0/68 existing-benign FP** — strictly
better than the mask on every axis.

**One tuning step, recorded because it is the trap in this approach.** The negative-term list
first contained `checklist`, which suppressed a genuine attack sample titled *"Release Checklist
Skill"*. A negative term must mean **"this code is being named as bad"**, never **"this document
is of a certain kind"** — a genre word is a title an attacker simply chooses. Removing it took
recall 2/3 → 3/3 with no FP change.

## Honest limits — read before shipping

- The populations are SMALL (3 attacks, 4 security-docs) and **I authored both**, so the 3/3 and
  0/4 are weaker evidence than they look. The 68 benign samples I did NOT author staying at 0 is
  the more independent signal.
- One term was removed AFTER seeing it cause a miss. That is overfitting pressure; the removal was
  principled and is argued above, but a second, blind-authored attack set would settle it properly.
- A negative-context suppressor is itself a silencing rule, so it inherits the standing hazard: it
  fails INVISIBLY when it silences too much. Whatever ships must surface what it suppressed, the
  way TRDD-3QIQ2E6J's `split_suppressed` trace does.

## Acceptance — SETTLED 2026-08-13, and the honest numbers are lower than the first ones

- [x] The 4 security-docs samples are in the benign corpus, so the mask's benefit stays priced
- [x] Whatever suppresses a match leaves a visible trace. NOTE the trace was first delivered as an
      opt-in `suppressed_out` argument that **no production caller passed** — a facility nobody
      calls is decoration, and the suppression would have been invisible exactly where it matters.
      `detectors/agent-context-integrity.py` now passes it and logs every suppressed match.
- [x] A blind-authored second attack set was measured. **It did NOT confirm the gain; it corrected
      it.** 6 samples per class, written from the rule descriptions with the regex unread:
      `dynamic-exec-in-body` 3/3 (100%) → **6/9 (67%)**. The discriminator was partly overfit to
      the three samples it was tuned against. Nothing was re-tuned to recover 100% — refitting to
      the new samples would destroy the only unbiased measurement in this card.
- [ ] ~~`dynamic-exec-in-body` reaches ≥3/3~~ — **this box was written against the biased sample
      and is retired, not ticked.** The defensible criterion is the LIKE-FOR-LIKE comparison on
      the full 9-attack / 72-benign set, which is what actually justifies the change:

      | | recall | FP |
      |---|---|---|
      | old fence mask | 3/9 | 0/72 |
      | shipped discriminator | **6/9** | **0/72** |

      Double the recall at zero false-positive cost, measured on a set where two thirds of the
      attacks were authored AFTER the fix. That is the claim this card supports. "100%" never was.

- [ ] REMAINS OPEN: 3 of 9 are still missed. They are not overfitting artifacts — they are real
      uncaught shapes, and a follow-up should characterise them rather than assume the rule is
      done. `two-step-code-injection` is flat at 3/9 (33%) and is the weaker of the two.

## Notes and lessons learned
