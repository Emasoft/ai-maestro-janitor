---
trdd-id: I6ZZWVDN
title: Measure the janitor's remaining two injected blocks — SessionStart compact and StopFailure rate_limit
column: todo
created: 2026-08-02T06:24:29+0200
updated: 2026-08-02T06:24:29+0200
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
