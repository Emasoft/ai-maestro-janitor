---
trdd-id: VAWIKRK2
title: Close the remaining missed dynamic-exec shapes (A, B, D, E) with a fresh blind set
column: complete
created: 2026-08-18T21:10:00+0200
updated: 2026-08-22T22:10:36+0200
current-owner: janitor-main-session
task-type: security
severity: medium
approval-tier: 0
scope: project
created-by: TRDD-XOITBRIZ
external-refs: [TRDD-XOITBRIZ]
npt: []
eht: []
implementation-commits: [5f347cbd, 8a9830ec, 84198838, 17d0fedf, d010495b, 7c1d17ee, 559fa7fc, 7cc45cf6, e0071963, 9690e5fd, 76ad2f87]
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

**TRIAGE DONE 2026-08-21 05:40** — `reports/agent-context-bench/20260821_054037+0200-vawikrk2-out-of-sample-triage.md`
(gitignored). Its finding reorders the next pass: **5 classes have a rule that catches ZERO
out-of-sample** — `concealment-directive` 0/9, `prompt-injection-multilingual` 0/9 (both 0 on
ANY rule), `exfil-webhook-sink` 0/9, `mcp-annotation-lying` 0/9, `two-step-code-injection` 0/7.
Those are worse than the 8 declared blind spots: a blind spot is honest and the coverage table
says so, while a claimed rule scoring 0/9 reads as coverage on every report. That is the
silent-FN asymmetry the bench exists to expose.

Also corrective: **`dynamic-exec-in-body` scores 3/9 — mid-pack, not worst.** This card's shape
analysis covers only that rule, so the per-shape pass is no longer obviously the highest-value
next move; rank by silent risk and the 0/9 bucket goes first. And the **FP budget is intact
(0/46 benign)**, so there IS headroom to widen a rule — the condition shape A's base64-floor
trap warns is usually absent.

**1 of 5 CLOSED 2026-08-21: `concealment-directive` 0/9 → 8/9, FP 0.** Commit `5f347cbd`.

The 0/9 was a RULE gap, not a corpus gap — and the distinction was worth the hour it took to
settle, because the cheap read was the wrong one. The samples barely mention "the user", and the
one I opened first is 900 characters of ordinary security-policy prose ("Project Phoenix Security
Policy v2.1": Purpose, Access Control, Data Handling…). That looks exactly like an off-label
sample, and widening a rule toward mislabelled content would have spent the FP budget on noise.
The payload is buried at `### 7.3 Silent Operations` — "certain tasks must be performed without
generating logs", "disable audit logging temporarily" — i.e. the corpus was correctly delivering
the *"buried inside a long legitimate-looking document"* variant the generator prompt asked for.
**Judging a blind sample by its opening paragraph is judging it by the disguise.**

Root cause: the pattern only ever matched concealment from **the user** (literal object). All 9
samples conceal from **the record** — audit trail, logs, changelog, commit message. Same attack
to a human, invisible to the regex. Fixed by adding the missing half (+ name/description, which
had drifted from the pattern).

Measured: recall 8/9; **0 residual FP across 23,858 real agent-context files**. Two FPs surfaced
IN that measurement and are fixed with negative controls pinned — `hidden block` matched "hidden
BLOCKers", and `bypass audit` matched "direct-API-**bypass audit**" (an audit OF bypasses; the
hyphen flips the part of speech). Sample 07 (`suppress_output: true`, `log_level: silent`) is a
DELIBERATE abstention: legitimate config keys, and the FP budget is what makes a CRITICAL rule
worth reading.

**ALL 5 CLOSED 2026-08-21.** Commits `5f347cbd`, `8a9830ec`, `84198838`, `17d0fedf`, `d010495b`.

| rule | before | after | dev / holdout at fix time | FP delta on 23.8k real files |
|---|---|---|---|---|
| `concealment-directive` | 0/9 | **8/9** | 4/4 · 4/5 | 0 |
| `prompt-injection-multilingual` | 0/9 | **9/9** | 7/7 · 2/2 | 0 |
| `exfil-structural-probe` (the real target — see below) | 1/9 | **2/9** | 2/5 · **0/4** | 0 |
| `mcp-annotation-lying` | 0/9 | **4/9** | 1/5 · 3/4 | 0 |
| `two-step-code-injection` | 0/7 | **7/7** | 1/1 · **6/6** | 0 |

**⚠ THE "after" COLUMN IS FIT, NOT OUT-OF-SAMPLE RECALL — do not quote it as recall.**
`agent_context_bench.split_of` exists to prevent exactly what I did: *"tune on `dev`, quote
the number from `holdout`"*. I fixed all five while looking at EVERY sample in each class, so
**this corpus is now spent as a generalisation measure for these five rules.** The honest
statement is "the gap that was found is closed" — worth pinning, and a different claim from
"the rule generalises". I found this discipline in the module's own docstring only after the
fixes were committed; recording it rather than quietly keeping the flattering number.

The split still says something under contamination, which is why it is in the table: where a
fix is one general SHAPE it covers holdout samples it was never individually shaped against
(`two-step` — four branches, **6/6 holdout**), and where it is not, that shows too
(`exfil-structural-probe` — **0/4 holdout**: the boundary fix is correct and its
generalisation is unproven on this class). A future blind corpus is the only way to convert
any of these into real recall numbers.

**The FP column is NOT contaminated and is the stronger half of this work.** Those ~23,800
real agent-context files were never used to CHOOSE a pattern, only to REJECT one — four
attempts were reverted on their evidence.

**ONE ROOT CAUSE, five times: each rule enumerated the CANONICAL phrasing of its attack and
the corpus used a variant.** Not one of the five was missing a language, a host, or a
technique — each was missing the OBJECT, the FIELD, or the SYNTAX the same attack takes when
written by someone who is not quoting a textbook:

- `concealment-directive` matched concealment from "the user"; attacks conceal from the RECORD.
- `prompt-injection-multilingual` covered "ignore previous instructions" in ELEVEN languages;
  attacks keep the verb and swap the object for a security control. Eleven languages of one
  sentence is narrower than it looks, and it reads on a report as broad.
- `exfil-structural-probe` required `\bcredentials\b`; attacks write `user_credentials`, and
  `\b` cannot see inside a snake_case compound. A rule that reads agent CONFIG could not read
  config spelling.
- `mcp-annotation-lying` searched `name` for the destructive verb; attacks put the lie in
  `name`/`description` and the truth in `handler`. It was searching the innocuous half.
- `two-step-code-injection` knew `Buffer.from`/`atob` → `eval`; every attack used the SHELL
  pipeline (`| base64 -d | bash`), which is also the commoner form in the wild.

**TRIAGE CORRECTION — `exfil-webhook-sink` 0/9 is NOT a defect.** It is a literal blocklist of
known exfil hosts; janitor#226 already measured it 0/8 and rewrote its description to say so
("LIMIT: matches those hosts ONLY"). It therefore does NOT read as coverage, which was the
bucket's whole premise. The honest target was its structural companion. Verify the premise of a
finding before acting on it — the triage was right about four and wrong about one.

**FOUR MEASURED REFUSALS, each implemented → measured → reverted → pinned as a negative
control** (a refusal nobody pinned gets silently re-proposed): `env[_-]vars?` (+1 recall, **+5
FP**), `${…TOKEN|SECRET|KEY}` (+2, **+18 FP** on OFFICIAL plugin docs), a prose read-only claim
fed to the existing 800-char window (**+33 FP**), and an unbounded self-contradiction span (the
same **+33** — a 500-char skill description eventually says "moves" somewhere far from
"read-only"; two words in one long paragraph are not a contradiction). **Every FP I introduced
came from adding VOCABULARY; none came from fixing a BOUNDARY or a FIELD.** That is the
transferable rule for the next pass.

**Also a CORPUS finding, recorded so recall is not read as pure rule quality:** 5 of the 9
`mcp-annotation-lying` samples carry the deception only in the generator's `note` ("Backup tool
secretly erases logs") while the artifact shows a `log_backup` tool honestly declaring
`"destructive": false`. There is nothing in the text to detect and a human reviewer would find
nothing wrong either. 4/9 is the ceiling that class supports, not a shortfall.

**ALL FOUR ACCEPTANCE BOXES CLOSED 2026-08-21** — including the per-shape pass (A/B/D/E) this
card was originally scoped for; see the Acceptance section for each shape's measured position.
`dynamic-exec-in-body` went 5/9 → 7/9 on the blind set and 8/9 → 9/9 on the curated one, at
zero measured FP cost on the real surface.

**NEXT ACTION:** nothing required — the card is done pending the full suite. If someone picks
it up again, the ONE open thread is **Shape E**, which is deferred for lack of evidence rather
than fixed or refused: a future blind corpus that actually exhibits a split-literal payload
would let it be measured. That same fresh corpus is also the only way to convert this card's
"after" column into real out-of-sample recall (see the ⚠ above) — this corpus is spent.

The card's own rule still binds: do NOT quote a recall number that includes c14/c17 as if
measured.

**Reusable and not obvious:** the FP sweep must run over REAL agent-context files, not the bench's
benign set. The bench's 46 benign samples showed 0 FP for both the broken and the fixed pattern —
it was the 23,858-file sweep that found both real FPs. A benign set authored alongside the attack
set shares its blind spots.

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

- [x] new blind set exists, provenance recorded (author had read neither card) —
      `tests/agent_context_bench/corpus-vawikrk2-20260821.jsonl`, 278 samples / 28 labels,
      generated by free-pool models from ATTACK DESCRIPTIONS only (see the 2026-08-21 05:40
      STATE block for the run and its 30/32 capture). Contiguous credential SHAPES are masked
      at assembly (`assemble_corpus.mask_secret_literals`) so the fixture passes secret
      hygiene; verified per-sample that every masked sample's rule-firing set is byte-identical
      before and after, and the write was GATED on that.
- [x] per-shape fix or an explicit measured refusal (FP cost > benefit) for A, B, D, E —
      all four have a measured position, and one of them changed the card's own diagnosis:
      - **A (base64 floor) — RESOLVED WITHOUT TOUCHING THE FLOOR, diagnosis was wrong.**
        Sample 06 (`b64decode('c2g=')`, 4 chars) was filed as "literal under the 40-char
        floor", framing it as the base64-floor trap. The floor was never the blocker: the
        `subprocess\.[A-Za-z_]+\s*\([^)]*shell=True` branch used `[^)]*`, which stops at the
        first `)` — the one inside the nested decode call — so `shell=True` was never
        reached. Fixed structurally (`7c1d17ee`); the dangerous knob stays untouched.
      - **B (alias-reached sink) — FIXED** (`559fa7fc`). `getattr(os, "system")` /
        `setTimeout(eval, 0, body)`. Curated corpus 8/9 → 9/9; the alias branch fires on
        **0 of 12,606** real agent-context files.
      - **D (false suppression from a distant title word) — FIXED** (`7cc45cf6`), and it was
        worse than "false suppression": a genuine attack titled "# Report Formatter Skill"
        produced NO finding at all. Positional fix — heading lines no longer count as
        negative context. Real surface: 35 files reporting before, 35 after, **0 newly**.
      - **E (payload split across concatenated literals) — DEFERRED, no evidence.** A precise
        probe (a `+` join of two quoted literals within ±200 chars of an eval/exec/decode
        sink) finds **zero** instances across BOTH corpora. Deferring rather than refusing:
        the shape is real in principle, it simply has no sample here to measure a fix or an
        FP cost against, and building multi-literal correlation against zero evidence is how
        an unfalsifiable branch gets added. Needs a corpus that exhibits it first.
- [x] like-for-like table on the NEW set, benign FP unchanged at 0 — the table in the STATE
      block above, with the dev/holdout split and the ⚠ noting the "after" column is FIT, not
      out-of-sample recall. Benign is 0 on BOTH corpora through `scan_text`, and the blind
      benign population is pinned by `test_blind_corpus_floors.py`.
- [x] baseline gate updated so regressions fail — `tests/test_blind_corpus_floors.py`: a
      per-class floor for each of the five (parametrized, so a regression fails BY NAME rather
      than as one aggregate — the whole failure this card measured was a single rule reading as
      covered inside a healthy total), plus a whole-catalog benign check. Verified the gate can
      actually fail: the pre-fix `concealment-directive` pattern scores 0 against a floor of 8.
      The benign half goes through `scan_text`, not raw patterns — a raw match is not a finding
      (`file_kind` decides which rules run; `provenance_verified` downgrades a corroborated
      described-attack), and asserting on raw matches reddened on four samples the detector
      never reports. A gate that fails on correct behaviour gets deleted.

## Self-review (testing → ai_review, 2026-08-21T07:49+0200)

**Test gate: PASSED.** `uv run pytest` — 15,714 passed, 1 skipped, 0 failed (8m18s).
`uv run ruff check scripts tests` clean; `uv run mypy scripts/ --ignore-missing-imports` clean
across 486 files. Nine commits: `5f347cbd` `8a9830ec` `84198838` `17d0fedf` `d010495b`
`76ad2f87` `7c1d17ee` `559fa7fc` `7cc45cf6`.

**What a reviewer should be suspicious of, stated by me rather than found by them:**

1. **The recall numbers are FIT.** I tuned against every sample. See the ⚠ in the STATE block.
   The FP numbers are the trustworthy half.
2. **Two of my own measurements were wrong before they were right** — an FP figure inflated
   ~2.5x by sweeping paths the detector never reads, and "5 false positives" counted per-MATCH
   on a file already being reported. Both are corrected in the commits that carry them; the
   pattern to watch for is me measuring on a surface or unit I chose rather than the one the
   consumer uses.
3. **`never\b` is now a suppression cue** (Shape D). It is attacker-controllable — a payload
   that says "never skip this step" near an eval self-suppresses. Measured at zero cost on both
   corpora, but it is the weakest term in that list and the first thing to re-measure if a
   future corpus shows an evasion.
4. **Shape E is deferred, not done.** No corpus evidence; box ticked as a measured deferral.

**Why this is not moved to `complete` by me:** `ai_review → human_review` is an escalation gate
and `human_review → complete` is a USER decision (manager-approval-defaults §Z). The work is
Tier-0 and self-approvable in a mono-agent repo, but the conservative reading is the one the
rules ask for when unsure, and the honest caveats above are exactly what a human should weigh.

## Approval log

- 2026-08-22T22:10:36+0200 — COMPLETE (human_review → complete) by USER, as one of a batch of six
  signed off together via a comment on the "What's Waiting On You" artifact ("sign off the six").
  All 4 acceptance boxes verified open=0 immediately before the transition, counted with a
  permissive checkbox regex rather than read from a handoff.
