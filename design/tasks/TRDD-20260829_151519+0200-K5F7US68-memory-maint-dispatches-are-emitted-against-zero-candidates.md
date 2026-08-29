---
trdd-id: K5F7US68
title: Memory-maint dispatches are emitted against zero candidates
column: backburner
blocked-by: []
created: 2026-08-29T15:15:19+0200
updated: 2026-08-29T15:15:19+0200
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

# TRDD-K5F7US68 — Memory-maint dispatches are emitted against zero candidates

## The measurement

Reported by the `emasoft-orchestrator-agent-96` peer session, **reproduced independently on
this project's own LOCAL root before filing** (not taken on trust):

```
memory_candidates_cli.py --intervention <iv> --scope local --root <LOCAL root>
  repair      -> 0 candidates
  atomize     -> 0 candidates
  consolidate -> 1 candidate
```

The peer measured the same three numbers against their root, over 8 queued dispatches
(3 repair, 1 atomize, 4 consolidate; oldest stamped 1787419847, 24h+ old).

## Defect A — a dispatch is emitted for an intervention with no candidates

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

1. Find why the emit-time precheck and `memory_candidates_cli.py` disagree for
   `repair`/`atomize`. Fix the emitter, not the agent.
2. `same-tier-type` must not be sufficient to emit a consolidate candidate. A grouping
   predicate for consolidation needs SUBJECT evidence (shared links, shared keywords,
   overlapping atom ids) — `(tier, type)` is metadata about SHAPE.
3. A dispatch whose candidate set is empty at CLAIM time should be dropped with a logged
   reason rather than handed to an agent. That is defence in depth, NOT the fix — if it is
   the only change made, the emitter still churns and the cost merely moves.

## Acceptance

- [ ] A repair/atomize marker is not emitted when its candidate predicate is empty.
- [ ] Consolidate requires subject evidence; the `same-tier-type`-only group no longer
      emits on either root measured here.
- [ ] A regression test builds a scope whose candidates are empty and asserts no marker.
- [ ] The 8 stale pending dispatches are dealt with explicitly (drop or drain) — decided
      once the emitter is fixed, so the decision is not made against churning state.

## Notes and lessons learned

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
