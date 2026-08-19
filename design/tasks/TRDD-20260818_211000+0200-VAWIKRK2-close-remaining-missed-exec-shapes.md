---
trdd-id: VAWIKRK2
title: Close the remaining missed dynamic-exec shapes (A, B, D, E) with a fresh blind set
column: todo
created: 2026-08-18T21:10:00+0200
updated: 2026-08-20T00:00:56+0200
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

## ⏵ STATE — 2026-08-20 00:00: full resume-run COMPLETED — 21/32 captured; the blocker is the 900 s CEILING vs CLASS WEIGHT, not pool availability

The 2026-08-19 ~20:23 resume-run (llm-ext restored to PATH — it vanished from the
non-interactive PATH; the repo-bundled `~/Code/llm-externalizer/llm-externalizer-plugin/bin`
prepend fixes it) drained all 32 jobs to a verdict. **Captured 21** (`c01-c12, c15, c16,
c21, c23, c24, c26, c28, b3, b4` — benign now PARTIALLY present, 2/4). **TIMED OUT 11 at
the 900 s per-call ceiling**: c13, c14, c17, c18, c19, **c20 two-step-code-injection**,
c22, c25, c27, b1, b2. c13/c14/c19/c20 reproduced their morning timeouts exactly, on a
quiet pool and a calm host — so the earlier "pool availability" theory is CORRECTED: these
classes' generation prompts are too heavy for the free tier inside 900 s, ever. The
measurement is STILL blocked by its own rule (c20 missing; benign only half present).

**NEXT ACTION (pick one, next session):** (a) raise the per-call ceiling for the 11 heavy
classes only; (b) run just those 11 through a paid or local profile (`--estimate` first per
the llm-ext cost rule); (c) split the heavy prompts. Keep it BLIND either way. The 21
captured .path files are preserved in `tests/agent_context_bench/out/` — resume skips them.

## ⏵ STATE — 2026-08-19 ~06:55: generation STOPPED — pool degraded to timeouts; box-1 blind set is PARTIAL *(superseded by 2026-08-20 above — the "pool availability" diagnosis was wrong)*

The background regen ran 12/32 classes then the free pool degraded to per-call TIMEOUTs (c13,
c14 both hit the 900s ceiling with no completion in ~30 min). Stopped it (`TaskStop bne4zye4w`)
rather than hammer the fleet-contended pool for ~2 more hours to produce a set STILL missing the
classes this card needs. Captured this run (12 `.path` files in `tests/agent_context_bench/out/`,
blind, preserved — a future full run's `[ -d out ] && mv out out.pre-vawikrk2.<ts>` moves them
aside, never clobbers): authority-override … through `mcp-annotation-lying` (c12), **including
`dynamic-exec-in-body` (c09)** — one of the two target classes. **NOT captured:
`two-step-code-injection` (c20) and `benign`** (both sit behind the c13 timeout wall), so the
out-of-sample recall + 0-FP measurement CANNOT be run yet.

**RE-RUN when the pool is quiet** (or targeted: the two attack classes + benign only — but keep
it BLIND, intent-only from `classes.tsv`, no shape-enrichment). Do NOT measure on the partial set
and quote a recall number — a set missing two-step + benign would understate coverage and has no
FP baseline. The blocker is now pool AVAILABILITY at generation time, not the feature.

## ⏵ STATE — 2026-08-19: free pool RECOVERED; a fresh BLIND corpus generation is RUNNING (background)  *(superseded above — pool degraded mid-run)*

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
