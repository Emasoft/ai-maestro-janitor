---
trdd-id: VAWIKRK2
title: Close the remaining missed dynamic-exec shapes (A, B, D, E) with a fresh blind set
column: todo
created: 2026-08-18T21:10:00+0200
updated: 2026-08-19T05:52:00+0200
current-owner: janitor-main-session
task-type: security
severity: medium
approval-tier: 0
scope: project
created-by: TRDD-XOITBRIZ
external-refs: [TRDD-XOITBRIZ]
npt: []
eht: []
---

# Remaining missed shapes from the fence-mask replacement (XOITBRIZ follow-on)

## ⏵ STATE — 2026-08-19: free pool RECOVERED; a fresh BLIND corpus generation is RUNNING (background)

The only thing blocking this card was the fleet-contended free pool (same 429 that failed the
PXP08ZQC probe). Re-probed 2026-08-19 ~05:51 → `llm-ext chat` rc=0, free model resolved. So the
blocker is CLEARED.

Kicked off the fresh blind set (box 1) as a background job: re-ran `tests/agent_context_bench/
generate_corpus.py` UNCHANGED into a fresh `out/` (the prior `out/`, if any, moved to
`out.pre-vawikrk2.<ts>`). This is blind BY CONSTRUCTION and honors "authored by something that
has NOT read XOITBRIZ or this card": the generator is llm-ext prompted with the intent-only
`classes.tsv` descriptions (which pre-date the shape analysis — NOT enriched toward shapes
A/B/D/E, which would encode post-hoc knowledge and void the out-of-sample property), and
`assemble_corpus.py` DROPS any malformed sample rather than repairing it, so no human authorship
leaks in. Gen log: session scratchpad `vawikrk2-gen.log`.

**NEXT ACTION when the generation completes:** (1) `assemble_corpus.py` the fresh `out/` into a
NEW corpus file (do NOT overwrite the committed baseline `corpus.jsonl`); (2) run
`agent_context_bench.py` against it for a clean out-of-sample recall + the 0-FP check on benign
(box 3); (3) per-shape (A base64-floor / B alias-sink / D positional-suppression / E
split-literal) decide a fix OR a measured refusal — NEVER quote the burned original blind set;
(4) update the baseline gate so a regression fails (box 4). The measurement+fix is a focused
security pass, not a marathon-tail edit — do it deliberately.

## Why

TRDD-XOITBRIZ replaced the code-fence mask with a prose discriminator (3/9 → 7/9 recall at
0/72 FP) and characterised every remaining miss into 5 shapes
(`reports/xoitbriz/20260813_120000+0200-missed-shapes.md`). Only shape C was safe to close on
existing evidence. Four remain, and the blind set is BURNED for this rule (shape C was fixed
after seeing which sample exposed it), so no further recall claim may quote it.

## What

- **Shape A** — literal under the 40-char base64 floor: knob-shaped, but the FP cost at a lower
  floor is UNMEASURED (this is the exact base64-floor trap the parent card recorded once) —
  measure before moving the knob.
- **Shape B** — sink reached by alias/reference (`getattr(os,"system")`,
  `setTimeout(eval, 0, body)`).
- **Shape D** — false suppression from a title word 260+ chars away: needs a POSITIONAL rule
  (headings are titles, never disclaimers), not more term-pruning — the parent card's own
  recurring lesson.
- **Shape E** — payload split across concatenated literals: needs multi-literal correlation, a
  different kind of matching than any current branch.
- **Fresh blind set FIRST**: authored by someone/something that has NOT read XOITBRIZ or this
  card, before any fix, so the resulting recall number is a clean out-of-sample measurement.

## Acceptance

- [ ] new blind set exists, provenance recorded (author had read neither card)
- [ ] per-shape fix or an explicit measured refusal (FP cost > benefit) for A, B, D, E
- [ ] like-for-like table on the NEW set, benign FP unchanged at 0
- [ ] baseline gate updated so regressions fail

## Approval log
