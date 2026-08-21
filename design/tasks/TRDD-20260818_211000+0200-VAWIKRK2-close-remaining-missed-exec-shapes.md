---
trdd-id: VAWIKRK2
title: Close the remaining missed dynamic-exec shapes (A, B, D, E) with a fresh blind set
column: dev
created: 2026-08-18T21:10:00+0200
updated: 2026-08-21T05:40:00+0200
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

## ⏵ STATE — 2026-08-21 05:40: **RUN COMPLETE 30/32 — MEASUREMENT RUN. Out-of-sample recall 39%, FP 0%.**

Generation finished: `ALLDONE 30/32`. Only **c14 whole-env-exfil** and **c17
procmem-credential-extraction** never produced output, at 1800 s, concurrency 1. Nine of the
eleven heavy classes were recovered by the ceiling raise — so options (b) paid/local and (c)
split-prompts now apply to TWO classes, not eleven.

**A parser bug nearly wasted the whole run — read this before trusting any corpus count.**
`assemble_corpus.objects_in()` walks a whole report tracking string/escape state, so ONE
malformed sample desynchronises it and silently swallows every LATER sample in that file. On the
c20 report it returned exactly ONE object — the 44-char output TEMPLATE echoed inside the prompt
— while 7 of 9 real samples (286-863 chars) were valid JSON on their own lines. The first bench
run therefore listed `two-step-code-injection` under **"rules with no corpus coverage"**, hours
after a run whose entire purpose was to capture it. Invisible in aggregate: corpus-wide the
walker finds MORE records than per-line parsing (301 vs 278), so totals looked healthy while one
class was missing outright. Fixed in `34577427` (per-line first, walker as fallback, seen-set
dedupes; strict superset 271 -> 278 samples, 27 -> 28 labels).

**THE MEASUREMENT** (`corpus-vawikrk2-20260821.jsonl`, blind, committed baseline `corpus.jsonl`
NOT overwritten):

```
samples 278 · attack(claimed) 168 · benign 46
recall (intended rule) 39%  ·  recall (any rule) 42%  ·  false positives 0%
```

**0% FP on 46 benign samples** — the 0-FP property survives out-of-sample, which is the half
this detector could most easily have lost.

**Recall 39% is the honest headline, and it is over 26 of 28 attack classes** (c14/c17 absent —
do not quote it as "the corpus"). The class this card exists for scores **0 of 7 intended** on
`two-step-code-injection`. Eight classes are declared blind spots and score 0-2 "any rule".

**NEXT ACTION:** per-shape decisions (A base64-floor / B alias-sink / D positional-suppression /
E split-literal) against THESE numbers, then update the baseline gate so a regression fails. The
card's own rule still binds: do NOT quote a recall number that includes c14/c17 as if measured.

## ⏵ STATE — 2026-08-21 05:05: c20 CAPTURED — the measurement's blocker is GONE. 25/32 *(superseded above)*

`c20 two-step-code-injection` landed at 1800 s / concurrency 1, having timed out at 900 s twice
before. That is the class whose absence made the out-of-sample recall + 0-FP measurement
unrunnable, so the card's central blocker is cleared.

Per-class verdict so far (this is the useful output — the previous runs produced one blanket
answer, this produces a routing decision per class):

| class | 900 s | 1800 s / conc 1 |
|---|---|---|
| c13 mcp-schema-in-annotations | TIMEOUT x2 | **ok** |
| c14 whole-env-exfil | TIMEOUT x2 | TIMEOUT |
| c17 procmem-credential-extraction | TIMEOUT | TIMEOUT |
| c18 git-protocol-only-dependency | TIMEOUT | **ok** |
| c19 dns-exfil-long-subdomain | TIMEOUT x2 | **ok** |
| **c20 two-step-code-injection** | TIMEOUT x2 | **ok** |

4 of 6 recovered by the ceiling raise alone. Only c14 and c17 are genuinely too heavy for the
free tier at 1800 s — those two, and only those two, are the candidates for option (b) paid/local
or (c) split prompts. The 08-20 conclusion that "these classes' generation prompts are too heavy
for the free tier inside 900 s, ever" was right about the ceiling being binding and wrong to
generalise it to all eleven.

Still running: c22, c25, c27, **b1, b2**. The benign set is the other half of the measurement's
own rule (b3/b4 already captured); with b1+b2 it is complete and the measurement is runnable.

## ⏵ STATE — 2026-08-21 03:15: OPTION (a) IS WORKING — c13 captured at 1800 s / concurrency 1 *(superseded by the block above)*

Took the previous block's option **(a) raise the ceiling**, with one addition its own data
already implied: **ceiling and concurrency are ONE lever.** This file had measured that a
SINGLE call completes in ~270 s while 4 concurrent pushed nearly every call past its timeout —
throughput is bounded by the pool, so every extra worker takes time away from each call in
flight. Two heavy calls sharing the pool is how both reach the ceiling. So the resume runs at
**concurrency 1**, not 2, giving one call the whole pool.

`generate_corpus.py` gained two env knobs (`BENCH_CALL_TIMEOUT_S`, `BENCH_WORKERS`), defaults
UNCHANGED at 900/2 so an ordinary full run behaves identically (commit `e0071963`). The
PROMPTS were not touched — they must stay byte-identical or the corpus stops being blind.

**First result: `c13 mcp-schema-in-annotations` CAPTURED.** It had hit the 900 s ceiling twice
before, on a quiet pool and a calm host. 22/32. Running: `BENCH_CALL_TIMEOUT_S=1800
BENCH_WORKERS=1`, free tier, $0, background task `b9ss3pdx5`. Remaining: c14, c17, c18, c19,
**c20 two-step-code-injection** (the class that blocks the measurement), c22, c25, c27, b1, b2.

If the rest also land, the measurement is unblocked with no paid profile and no prompt surgery.
If some still time out at 1800 s, THAT is the evidence for options (b)/(c) — and it is now a
statement about those specific classes rather than about the pool.

## ⏵ STATE — 2026-08-20 00:00: full resume-run COMPLETED — 21/32 captured; the blocker is the 900 s CEILING vs CLASS WEIGHT, not pool availability *(superseded by 2026-08-21 above — the ceiling was the blocker, and raising it works)*

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
