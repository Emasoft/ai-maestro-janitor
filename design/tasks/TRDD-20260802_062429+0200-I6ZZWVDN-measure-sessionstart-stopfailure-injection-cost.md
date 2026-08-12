---
trdd-id: I6ZZWVDN
title: Measure the janitor's remaining two injected blocks — SessionStart compact and StopFailure rate_limit
column: backburner
review-after: 2026-09-11
created: 2026-08-02T06:24:29+0200
updated: 2026-08-12T11:20:00+0200
current-owner: claude-ai-maestro-janitor
task-type: spike
severity: MEDIUM
scope: project
release-via: none
parent-trdd: null
relevant-rules: []
implementation-commits: []
---

# Measure the janitor's remaining two injected blocks (SessionStart:compact, StopFailure:rate_limit)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative)

### 2026-08-12 — re-checked; `testing → backburner`, and the incidental is now a real card

**The one open row is unchanged and STILL cannot be forced.** `StopFailure:rate_limit` has not
fired since **2026-07-17** — re-verified today: `stop-failure.log`'s last four entries are all
`2026-07-17T20:16–20:20` (session `c8a95d7e`), `window-exhaustion.jsonl` stops at
`2026-07-17T20:20:25`, no `rate-limited.flag`, and **0 entries dated today**. Twenty-six days.

**That is not a stalled measurement — it is the rotator working.** The hook fires on a
rate-limit that ends a turn; the OAuth rotator exists to make that not happen, and on this host
it has (rotation fired 2026-08-11 10:00:13 across 3 accounts). So the blocker on this card is a
*symptom of another feature succeeding*, which is worth saying plainly: waiting is correct, and
"still unmeasured after 26 days" is a good outcome wearing the shape of a stalled one.

Moved to `backburner` with `review-after: 2026-09-11` because `testing` asserts someone is
testing, and nobody can — there is no step to pull until a real rate limit occurs. Everything
this card CAN answer, it answered on 2026-08-02.

**The incidental finding is now carded — it had never been.** `IDLE_TTL_EXPIRY` (81
occurrences / 2,676,704 tokens / $15.39, 47% of that session's waste) is **TRDD-B07VPT2G**.
Note what it took: this card correctly wrote that *"an NPT written as a bullet is a task nobody
can see on the board"* — and then recorded the extraction as an inline SECTION of itself, where
it sat for ten days. **A routing decision is not a routing action.** The section below is kept
as-is for its analysis; B07VPT2G now owns the work.

### 2026-08-02 — MEASURED. One row answered, one row NOT measurable yet (`todo → testing`)

Report: `reports/I6ZZWVDN/20260802_070929+0200-sessionstart-stopfailure-injection-cost.md`
(gitignored). Session `e804d2c9`, opus-5, 221 breaks / 5,643,196 wasted / $32.45.

**`SessionStart` → verdict (b): real, once per session, and NOT fixable by shrinking it.**
It appears as `hook: SessionStart:resume` with **`occurrences: 1`** — exactly the budget
TRDD-K1RJUYGK set as acceptable, against `PostToolUse:Edit` at 51 and `PreToolUse:Bash` at 32 in
the same table. Three findings that decide the "no action" call:

1. **Not attributable to the janitor from the label.** The label names the EVENT, and **nine**
   things register on `SessionStart` (8 plugins + `~/.claude/settings.json`). Unlike `Stop` — where
   SLFMG704 checked every registrant and found none injects — the janitor **is** a genuine
   contributor (its breadcrumb / TRDD-STATE / arm-nudge go to stdout, which the spec says becomes
   context). So the true claim is *"one of ≥9 contributors to a once-per-session block"*, never
   *"the janitor's 263k"*.
2. **The 263,023 tokens are POSITIONAL, not the block's size.** A prefix break re-bills everything
   after the changed block, so the figure measures where it sits, not how big it is.
3. **Therefore shrinking the janitor's output cannot fix it** — that is precisely the remedy
   TRDD-YRPUSIFY shipped and that was falsified: the block is re-written regardless of what it
   says. And even removing the janitor's contribution entirely leaves the break, because the other
   eight registrants still change the block.

**`StopFailure:rate_limit` → NOT resolved, and deliberately not claimed as cleared.** It is absent
from the report — but the hook **has not fired since 2026-07-17**: `stop-failure.log` has 0 entries
dated today (last four all 2026-07-17T20:16–20:20, session `c8a95d7e`), its own
`window-exhaustion.jsonl` artifact stops at `2026-07-17T20:20:25`, and there is no
`rate-limited.flag`. Absence is only evidence if the thing ran; calling this clean would be the
same error as declaring a detector healthy from a run in which it never executed. **To resolve:
re-measure a session whose `stop-failure.log` shows a same-day fire.** It cannot be forced honestly
— it needs a real rate-limit.

**`SessionStart:compact` specifically was not observable here and that is expected**, not a gap in
the method: this session started by RESUME, and an in-session auto-compaction fires `PostCompact`,
not a fresh `SessionStart`. Only a session a compaction actually started can show `:compact`.

**Incidental, and larger than this card's subject — routed, not buried.** `IDLE_TTL_EXPIRY` cost
**81 occurrences / 2,676,704 tokens / $15.39** in this one session — 47% of its total waste and
~10× the SessionStart row. That is TRDD-EUWIHP0G's subject (cold-cache compact), measured live.
Also: across 914 request bodies in 17 sessions, the cross-session classifier's `HOOK_INJECTION`
cause does **not appear at all** among its 8 ranked causes or 12 ranked actors — hook injection is
not a leading cost anywhere in the scan.

**Tooling note for the next run:** `--full` is required on both `get_cache_break_report` and
`get_cache_break_causes`; without it the payload is silently shaped to the top 5 and the
`_truncated` notice is easy to miss (it cost a wrong "HOOK_INJECTION is absent" reading here until
the untruncated pull contradicted the truncated one).

**Not started. Extracted from TRDD-SLFMG704 on 2026-08-02**, where it sat as an inline "NPT"
bullet on a card whose own scope (hand the cache-thrash finding to OTHER plugins) had finished.
It is the janitor's OWN remaining cost, so it does not belong on a cross-project handoff card —
and an NPT written as a bullet is a task nobody can see on the board (rule 9: derived tasks are
their own depth-1 TRDDs).

## What was measured, and what was not

TRDD-K1RJUYGK fixed the janitor's two **no-matcher PreToolUse** hooks — the `$8.60 / 712-break`
and `$4.48 / 37-break` offenders. It did NOT touch the other two janitor-attributed rows from the
same `agentlenspro get_cache_break_report` run:

| Block | Waste | Occurrences | Status |
|---|---|---|---|
| `hook: SessionStart:compact` | $6.31 | 7 | **unmeasured** — may be irreducible |
| `hook: StopFailure:rate_limit` | $5.45 | 7 | **unmeasured, and suspicious** |

Both need MEASURING, not assuming, and they pull in opposite directions:

- **SessionStart legitimately injects once per session** (the memory breadcrumb + the TRDD STATE
  surface). Once-per-session is the budget K1RJUYGK's own fix set as acceptable, so the honest
  outcome here may well be "this cost is correct, do nothing" — which is a result worth recording,
  not a failure.
- **`StopFailure`'s output is documented as IGNORED by the harness.** A break attributed to a hook
  that cannot inject is evidence the label names a *boundary* where the host's own prefix changed,
  not an *emitter*. SLFMG704 proved exactly this shape twice over for `hook: Stop` and
  `hook: PostToolBatch` (the latter has ZERO registrations on this machine, across 474 audited).
  So the likely finding is that this row is not the janitor's at all — but "likely" is what this
  card exists to replace.

## Do not change anything before the measurement

Both prior attempts at this class of fix were wrong in the same way. TRDD-YRPUSIFY bucketed the
injected TEXT and shipped with passing tests; the block is stripped regardless of what it says, so
the fix did nothing while looking done. The rule that came out of it stands: **a green unit test is
not evidence here.** Re-run `agentlenspro get_cache_break_report --sessionId <new session>` and show
the named block has LEFT `topOffenders`.

## Verification

- A report from a NEW session naming, for each of the two rows, one of: (a) it is the host's, not
  the janitor's — with the same boundary-vs-emitter evidence SLFMG704 used; (b) it is the
  janitor's and irreducible at once-per-session — with the per-session count shown; or (c) it is
  the janitor's and reducible — in which case that fix is its own card, gated on the same
  falsification.
- `release-via: none` — a measurement ships nothing by itself.

## Notes and lessons learned
