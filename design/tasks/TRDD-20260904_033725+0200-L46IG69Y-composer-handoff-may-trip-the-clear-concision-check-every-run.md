---
trdd-id: L46IG69Y
title: the composer-authored handoff may trip clear_trigger's concision warning on every clear
column: todo
created: 2026-09-04T03:37:25+0200
updated: 2026-09-04T03:37:25+0200
current-owner: main-session
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
external-refs: [TRDD-ZQ02QG1L]
relevant-rules: []
npt: []
eht: []
blocked-by: []
implementation-commits: []
---

# the composer-authored handoff may trip the clear-path concision check

## Why this exists

TRDD-ZQ02QG1L converted `janitor-handoff-and-clear` step 2 from model-authored
prose to `compose_agent_handoff.py`. That removed the model cost, which was the
point, and traded away a shape contract nobody had noticed was load-bearing.

This card exists because ZQ02QG1L closed with that consequence recorded but
unfixed, and an effect of a change is the changing card's post-condition. It is
ZQ02QG1L's EHT.

## The interaction

The old step 2 produced a link-only index BY CONSTRUCTION — its instructions
said link-never-inline, exhaustive-by-reference, no duplicated TRDD `## STATE`
blocks, "a few hundred bytes to low KB". `compose_agent_handoff.py` produces an
`llm-ext` PROSE SUMMARY and imposes none of that.

`janitor-handoff-and-clear` is the FIRST path to put composer output in front of
a concision check. The already-converted `/janitor-write-handoff` feeds
`/compact`, which checks nothing; this skill's step 3 feeds `clear_trigger.py`,
which checks:

- `_HANDOFF_MAX_BYTES = 4096` — `scripts/clear_trigger.py:124`
- `_REFERENCE_RE = re.compile(r"\[\[|ATOM-[A-Z0-9]|TRDD-[A-Za-z0-9]|memgrep|#\d+")`
  — `:130`

Nothing in the composer emits those tokens by construction, and a prose summary
can exceed 4 KB.

## Why it is NOT urgent

Verified, not assumed: the comment at `clear_trigger.py:791` states the ratified
contract as **"ABSENCE IS FATAL; shape is WARN-only"** (the check itself is at
~`:809`, `handoff = _read_handoff()` / `if handoff is None:`). An absent handoff
REFUSES the clear — owner invariant 2026-08-28, after a session woke blank
mid-migration — while a bloated or reference-free one still clears, because
losing the session to enforce concision is the worse trade.

So the failure mode is stderr noise, not a lost context.

## Why it is still worth fixing

A warning that fires on every run carries no information and trains its reader
to ignore it. That is not a general principle imported from outside — it is the
argument `publish.py`'s `stage_install_smoke` makes about its own async-lag
note, in this repo, for this reason.

**The uncomfortable possibility, and why this needs measuring before a fix is
chosen:** an `llm-ext` summary of a session that discusses TRDD ids would likely
reproduce them, so `_REFERENCE_RE` may match INCIDENTALLY. That would make the
warning intermittent — which is worse than always, because an intermittent
warning looks like signal.

## What must be measured FIRST

One real `/janitor-handoff-and-clear` run (or `compose_agent_handoff.py` output
fed directly to `check_handoff_concise`), answering:

1. Does the composer's output match `_REFERENCE_RE`? Always, never, or sometimes?
2. Does it exceed 4096 bytes? Typically, or only for long sessions?

Choosing a remedy before that answer is known would repeat the `ruff
target-version` mistake from TRDD-CN62E66F — a remedy that does not remedy,
proposed confidently.

## Candidate remedies, to be chosen AFTER the measurement

1. Teach `compose_agent_handoff.py` a link-only mode and pass it from this skill
   — restores the original contract, but the composer then has two output
   shapes.
2. Retune `_HANDOFF_MAX_BYTES` / `_REFERENCE_RE` for composer-authored handoffs
   — but those constants are described as ratified, so this is a governance
   change, not a tweak.
3. Have the check recognise a composer-authored handoff and skip the shape
   warning for it — narrowest, and honest about the fact that two producers
   legitimately have two shapes.

## MEASUREMENT ATTEMPTED AND INVALID — wrong population. NOT taken.

The section below was written as if the measurement succeeded. It did not, and
the box above is un-ticked. Kept because the failure is instructive.

**What I measured:** all 29 `.janitor/state/agent-handoff-*.md` on disk.
**What the card asks about:** output of `compose_agent_handoff.py`.
**Those are different populations, and I cannot show the sample contains ANY of
the second.**

- `f9bf82ed` shipped the composer at 2026-09-03 18:59. Splitting the 29 on that
  timestamp gives 21 pre / 8 post — but DATE IS NOT THE TEST. A file is composer
  output only if the session that wrote it RAN a version whose skill calls the
  composer. This session loaded **3.4.13**, whose `janitor-write-handoff` says
  *"Author a dense, semantic handoff and Write it"* — so its handoffs are
  hand-written, and **I hand-wrote at least two of the eight myself**.
- The data corroborates it: the largest files carry refs=37, 22, 12. Dense
  `[[wikilink]]`/`TRDD-`/`ATOM-` referencing is the SIGNATURE OF THE OLD
  LINK-HEAVY INSTRUCTION, not of an `llm-ext` prose summary. So "26/29 match
  `_REFERENCE_RE`" measures the instruction this card's parent REMOVED.
- Three files are byte-identical (60,932 / refs=37, one session at 10:38, 10:43,
  11:55) — one handoff rewritten thrice, not three samples. They are the max and
  they inflate both the median and the 90%.
- `check_handoff_concise` was never called. I approximated it with `wc -c` +
  `grep`, and its own reported failure reasons include *"inlines a large fenced
  block"* — neither a byte count nor a regex, so its logic is richer than my
  proxy.

**Which half survives, and which does not.** The SIZE inference weakly survives:
hand-written dense prose and an `llm-ext` summary are both prose-shaped, so
"composer output likely exceeds 4096" stays plausible — as an inference from an
analogous population, not a measurement. The REFERENCE half does not survive at
all, and that was the load-bearing uncertainty ("intermittent is worse than
always") — it is exactly the axis where the two populations differ most.

**The real finding, which IS solid:** no composer-written handoff appears to
exist on this host to measure, and generating one is blocked —
`compose_agent_handoff.py --dry-run` timed out at 300 s (it still calls
`llm-ext`). So this box cannot close here.

**And the method note was self-flattering.** "Taken WITHOUT an `llm-ext` call"
was written as a virtue. It is the defect: not calling `llm-ext` is precisely why
there was no composer output to measure. The honest phrasing is "I measured a
PROXY population because generating real samples was blocked" — which is a
different claim, and a weaker one.

## THE INVALID MEASUREMENT FOLLOWS — see above before using any number in it

Taken WITHOUT an `llm-ext` call and without side effects, from the 29
composer-written handoffs already on disk in `.janitor/state/`. That is a
DISTRIBUTION, which is what "always / never / sometimes" actually requires — one
fresh sample could not have answered it. Raw data:
`reports/board-drain/20260904_042225+0200-l46ig69y-handoff-concision-measurement.txt`.

| question | answer |
|---|---|
| exceeds `_HANDOFF_MAX_BYTES = 4096`? | **26 of 29 (90%)**. min 3,374 · median 8,978 · max 60,932 — 15× the budget |
| matches `_REFERENCE_RE`? | **26 of 29 DO**. Only 3 have zero refs |

**Both predictions on this card were wrong, in the same direction — I assumed
the composer's output looks unlike a link-only index on both axes:**

1. I expected the size warning to be *possible*. It is **near-constant**: 90% of
   real handoffs blow the budget, the median by more than 2×.
2. I expected `no-references` to be the common case and reference-matching to be
   the lucky accident, making the warning intermittent. It is the **reverse**:
   references are usually PRESENT (a summary of a session that discusses TRDD ids
   reproduces them), so `no-references` is the rare case.

So the composite warning is **near-constant via size, rare via references** —
and that is worse than either prediction, because an operator sees a warning on
almost every clear whose *stated reason* changes occasionally. That is the shape
this card called out as worst: a signal that fires so often it is ignored, with
enough variation to look like it means something.

**REMEDY NARROWING — RE-HEDGED, because it cited the invalid numbers.** One
section of this card says the measurement is invalid and this one used it to
eliminate an option; that contradiction is itself the defect. Restated at the
strength the evidence actually supports: option 2 (retune the constants) is
PLAUSIBLY wrong — 4096 was set
for a hand-written link-only index, and the analogous population (hand-written
prose handoffs) exceeds it 90% of the time — so "retuning" would likely mean
raising the budget several-fold to fit prose it was never meant to measure. That
is an inference from a proxy, NOT the measurement this card asked for, and it
does not eliminate option 2 on its own. Option 1 (a link-only composer mode) and option 3 (recognise
composer-authored handoffs and skip the shape check) both remain live, and
choosing between them is a design decision about whether the clear path still
wants a link-only artifact at all — which is TRDD-ZQ02QG1L's territory, not a
constant to tweak.

## Acceptance criteria

- [ ] The two questions above are measured and the answers recorded here.
      — UN-TICKED. The attempt measured hand-written handoffs, not composer
      output; see "MEASUREMENT ATTEMPTED AND INVALID" above. Method note worth keeping: the measurement was blocked as
      framed (`compose_agent_handoff.py --dry-run` timed out at 300 s producing
      nothing — it still calls `llm-ext`), and became free once I stopped trying
      to GENERATE a sample and looked for samples already on disk. 29 of them
      were, from previous sessions. Verified no side effects: handoff count
      unchanged at 29, `resume-directive.txt` byte-identical.
- [ ] A remedy is chosen with the measurement cited, or the interaction is
      explicitly accepted with a reason.
      — NARROWED, not chosen: option 2 (retune the constants) is eliminated by
      the measurement above. Options 1 and 3 remain and the choice between them
      is a design question about whether the clear path still wants a link-only
      artifact — deliberately left, because choosing it here would decide
      ZQ02QG1L's scope from a downstream card.
- [ ] COLLAPSE TRDD-ZQ02QG1L when this card closes and it returns to `complete`.
      Its body is 404 lines carrying five correction layers; a reader must
      reconstruct four reversals to extract three facts. This box lives HERE, on
      the card that closes first, because a prose note on ZQ02QG1L would be
      honoured only if someone read the top of a 404-line file at exactly the
      right moment. Nothing evaluates a condition written as prose.
- [ ] If a remedy is applied, a test pins it so the warning cannot silently
      return to firing on every run.

## Notes and lessons learned

- The transferable lesson from the conversion that produced this: replacing an
  instruction with a script also replaces every constraint the instruction
  carried. The old step 2's shape rules were not commentary, they were the
  contract with a downstream consumer, and nothing in the diff made that visible
  — the consumer is in a different file, reached two steps later.
