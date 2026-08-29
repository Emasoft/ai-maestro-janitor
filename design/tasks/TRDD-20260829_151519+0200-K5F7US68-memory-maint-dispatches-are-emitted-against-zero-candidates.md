---
trdd-id: K5F7US68
title: The memory-maint dispatch queue does not drain dedup or expire
column: backburner
blocked-by: []
created: 2026-08-29T15:15:19+0200
updated: 2026-08-29T15:17:33+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 3
severity: HIGH
effort: M
min-approval-requirement: none
task-type: bugfix
labels: [memory, dispatch, cost]
release-via: publish
test-requirements: [unit]
---

# TRDD-K5F7US68 — The memory-maint dispatch queue does not drain, dedup or expire

## The measurement

Reported by the `emasoft-orchestrator-agent-96` peer session. I re-ran the CLI on this
project's own LOCAL root and reported it as an independent reproduction — **it was not one; see
the retraction below**:

```
memory_candidates_cli.py --intervention <iv> --scope local --root <LOCAL root>
  repair      -> 0 candidates
  atomize     -> 0 candidates
  consolidate -> 1 candidate
```

The peer measured the same three numbers against their root, over 8 queued dispatches
(3 repair, 1 atomize, 4 consolidate; oldest stamped 1787419847, 24h+ old).

## ⛔ RETRACTED SAME DAY — Defect A is NOT a gate defect. Read this before the section below.

**2026-08-29, ~1h after filing.** The reporting peer retracted their own framing and they are
right. The section below is preserved as the WRONG diagnosis, because the error is instructive
and because acting on it would have been wasted work.

**The flaw:** candidates were measured NOW; the dispatches were stamped DAYS ago. Those are
different claims. This project's own report archive shows the gate was very likely CORRECT when
it fired — a repair dispatch stamped 1787747541 (2026-08-26 14:32) corresponds to a pass that
found 2 candidates (`nested-only-dates`) and committed 2 repair txns; one stamped 1787876877
(2026-08-28 02:27) found `missing-key:ocd` and backfilled it. Those passes consumed OLDER
dispatch_ids than the records still queued.

**Corrected diagnosis: the queue does not DRAIN and does not DEDUP.** Dispatches accumulate
faster than agents consume them; claiming is LIFO-ish in effect, so a fresh pass grabs a newer
record while older ones age; by the time an old record is worked, its candidates have already
been repaired by some other pass. The fix is drain / dedup / expiry, NOT gate correctness.

**The observable cost is unchanged and still real** — 8 records queued, oldest 2026-08-22, and
two ~190k-token spawns to discover zeroes. Only the cause moved.

**I made the same error and called it corroboration.** I ran the candidates CLI on my own LOCAL
root, got `repair 0 / atomize 0 / consolidate 1`, and reported it as an independent reproduction.
It was not: I measured the same wrong thing on a different root. Matching numbers felt like
confirmation and were only a second instance of the identical category error. **Two measurements
agreeing is not evidence when both measure the wrong quantity** — the peer, not the agreement,
caught it.

Also corrected: `consolidate -> 1 candidate` is a count of LINES. The single line carries all 9
filenames — one GROUP, not one page.

## Defect A (AS ORIGINALLY FILED — SUPERSEDED ABOVE) — a dispatch is emitted for an intervention with no candidates

`repair` and `atomize` markers are queued while their OWN candidate predicate returns
nothing. The scheduler is documented as running a content precheck before emitting a
marker (the heartbeat-protocol rule says so explicitly, and tells the agent NOT to
substitute its own measurement to decline). Either that precheck does not run for these
interventions, or it disagrees with `memory_candidates_cli.py`.

**The cost is the reason this is HIGH and not LOW.** Each marker spawns a background agent
whose whole job is to discover a zero the CLI answers in under a second. The peer burned
~380k subagent tokens on two spawns (consolidate, then repair) that both abstained, before
reproducing both verdicts in one cheap loop. Draining their remaining 8 would cost ~1.5M
tokens to reproduce verdicts already proven.

**The precheck/predicate disagreement is the bug to find** — not the abstention. An agent
that abstains is behaving correctly; janitor#260 explicitly forbids it from declining on a
self-measurement, so the agent CANNOT be the place this is fixed.

## Defect B — the consolidate candidate is a false positive by construction

Already tracked as **janitor#64** (consolidate re-abstain); recorded here because the two
now have a measured shared cause and should be fixed together.

The candidate is emitted with reason `same-tier-type`. On this project's LOCAL root it
groups pages whose subjects are: publish-blocked persistence, CC changelog currency, CPV
false positives, rotator 429 version skew, publish carry-over. On the peer's root it groups
nine pages spanning TRDD CLI auth, AMP identity collision, CC hook stdout schema, a CPV FP,
a publish CI flake, per-agent state location, the plugin abstraction principle, and plugin
cache flushing.

**Sharing `(tier, type)` is not sharing a SUBJECT.** Merging any of these groups would
violate the wikimem "one page = one subject" law the corpus is built on, so the candidate
can never be actionable — yet it re-emits every cadence and re-queues.

The corpus is already documenting the loop: one of the peer's nine pages is
`reference_janitor-consolidate-reabstain-noop`.

## Scope

1. ~~Find why the emit-time precheck and `memory_candidates_cli.py` disagree~~ — **DROPPED,
   retracted above.** The gate was right when it fired. Instead: make the queue DRAIN, DEDUP and
   EXPIRE. A record whose candidates were repaired by a later pass must age out on its own; two
   records naming the same (scope, root, intervention) must collapse to one; claiming must not
   leave old records to starve while newer ones are taken.
2. `same-tier-type` must not be sufficient to emit a consolidate candidate. A grouping
   predicate for consolidation needs SUBJECT evidence (shared links, shared keywords,
   overlapping atom ids) — `(tier, type)` is metadata about SHAPE.
3. A dispatch whose candidate set is empty at CLAIM time should be dropped with a logged
   reason rather than handed to an agent. That is defence in depth, NOT the fix — if it is
   the only change made, the emitter still churns and the cost merely moves.

## Acceptance

- [ ] The queue DRAINS: a record whose candidates a later pass repaired ages out on its own.
- [ ] The queue DEDUPS: two records naming the same (scope, root, intervention) collapse to one.
- [ ] Consolidate requires subject evidence; the `same-tier-type`-only group no longer
      emits on either root measured here.
- [ ] A regression test builds a scope whose candidates are empty and asserts no marker.
- [ ] The 8 stale pending dispatches are dealt with explicitly (drop or drain) — decided
      once the emitter is fixed, so the decision is not made against churning state.

## Notes and lessons learned

- 2026-08-29 — **A measurement taken NOW cannot falsify a decision taken THEN.** The whole
  wrong diagnosis rests on comparing today's candidate count against dispatches stamped days
  earlier. Both the peer and I did it, got matching numbers, and read the agreement as
  corroboration. It was the same category error run twice. **Before calling a stale queue entry
  wrong, ask what was true when it was written** — here the report archive answered it outright.
- 2026-08-29 — **A precheck nobody can audit is indistinguishable from no precheck.** The
  heartbeat protocol tells the agent to trust the emitter's precheck and forbids declining
  on its own measurement — sound, because a cheap local measurement disagreeing with the
  scheduler is exactly how work gets skipped. But it means a broken precheck can only be
  discovered by paying for the spawn, and the agent that pays cannot report the disagreement
  as a defect. **When you forbid a consumer from second-guessing a producer, the producer
  needs its own test.**
- 2026-08-29 — **The peer's conduct correction is worth keeping.** They ran
  `memory_dispatch_claim.py` as a "verification" probe and it CONSUMED a real claim — the
  claim step is not side-effect-free. A probe that mutates the queue it is inspecting is a
  trap the script's own name does not warn about; worth a guard or a `--dry-run`.
