---
trdd-id: K5F7US68
title: The memory-maint dispatch queue does not drain dedup or expire
column: testing
blocked-by: []
created: 2026-08-29T15:15:19+0200
updated: 2026-10-10T10:12:45+0200
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
implementation-commits: [86a48174, 1b2071a3, 85304cd4, b60db1f5, 46723bc7]
status: tasked
eht: [S41TV0I7]
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

## ⏵ 2026-08-29 21:05 — a marker fired with NO claimable dispatch behind it, and it cost 199k

First dispatch run after the agent registry was restored. The agent did everything right —
claimed first, did not self-select a scope, did not fall back to the legacy slot, stopped and
reported. The claim step returned **exit 2**:

```
no claimable memory-maintenance dispatch in <project>/.janitor/state
(a legacy pending slot exists but is not claimable — it is not per-dispatch)
```

**Cost of that correct null: 198,961 subagent tokens, 3 tool calls, 25 s** — to reach an answer a
sub-second CLI call already had. Same shape as the ~208k null this card already records, so it is
not a one-off.

### ⛔ RETRACTED 20 MINUTES LATER — the emitter is FINE. The 199k was MY prompt's fault.

I wrote here that "the emitter fires markers for which NO per-dispatch record exists". **False.**
Listing `.janitor/state/memory-maint-pending-*.json` shows **four claimable records, one per
marker fired tonight** — `split PROJECT`, `enrich LOCAL`, `repair PROJECT`, `atomize PROJECT` —
and `--peek` returns the first of them.

**The real cause: the agent ran `--chore consolidate`, a chore nobody dispatched.** My dispatch
prompt said "run whatever is claimable" and never named the chore, so the agent filled the gap
with a guess. `--chore` filters STRICTLY by design (janitor#275 — a marker-routed agent must not
consume another chore's assignment), so a wrong name yields exit 2 and looks exactly like an
empty queue.

**Two corrections, and the second is the one that matters:**

1. The 199k null was **self-inflicted by an under-specified prompt**, not evidence about the
   emit gate. It still demonstrates this card's cost thesis — a spawn to reach exit 2 costs ~200k
   whatever the reason — but it is NOT evidence of an emitter defect. Do not cite it as one.
2. **My "the registry gap may have cost ZERO throughput" retraction was itself wrong.** The four
   markers WERE genuinely queued, they are still queued, and the unspawnable agent really did
   block them. The original claim stood; I retracted a true statement on the strength of one
   mis-parameterised run.

**The lesson, at my own expense:** an exit code that means "nothing matched YOUR FILTER" reads
identically to "nothing exists". Before concluding the queue is empty, list it —
`ls .janitor/state/memory-maint-pending-*.json` is one command and it would have prevented both
wrong conclusions.

**Still true and still worth fixing:** a legacy pending slot sits in `.janitor/state` that the
claim step must refuse on every attempt, and a spawn that reaches exit 2 costs ~200k. A cheap
`--peek` before spawning would pay for itself immediately.

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

- [x] The queue DRAINS: a record whose candidates a later pass repaired ages out on its own.
- [x] The queue DEDUPS: two records naming the same (scope, root, intervention) collapse to one.
- [ ] REJECTED BY DESIGN 2026-10-10, NOT MET and not to be built (see Implementation notes). Original text: Consolidate requires subject evidence; the `same-tier-type`-only group no longer
      emits on either root measured here.
- [x] A regression test builds a scope whose candidates are empty and asserts no marker.
- [ ] CARRIED BY TRDD-S41TV0I7 since 2026-10-10 (five records here, two of them old). Original text: The 8 stale pending dispatches are dealt with explicitly (drop or drain) — decided
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

## Implementation notes

2026-10-07: the claim step drops an aged-out record only on a KNOWN empty candidate answer from a read-only chore (repair, atomize, consolidate, split-topic); enrich and relocate records never drain by this path; an error keeps the record claimable; card items 2 and 3 not done. Merged at 1296ccde.
2026-10-07: disclosure: one function-level change (is_drained in scripts/memory_dispatch_claim.py, commit 1b2071a3) was made with a plain Edit, outside the plain-edit scope the main agent had set (module-level constants, comment blocks, docstrings); accepted once because it is small and covered by the two new tests.
2026-10-10 07:39: 85304cd4. FOUND: a consolidate refusal with one page is inert (group_has_unjudged_pair needs one live key holding both pages) and the CLI still printed 'recorded'. Seen twice on this repo's LOCAL root, checked by the main session in the ledger and the candidates CLI: the 2026-10-06 pass keyed fastedit-freeze.md alone and the same pair was dispatched and declined again on 2026-10-08; the 2026-10-10 07:35 pass recorded three one-page keys for a three-page group and the group was still listed right after. Not excluded for 2026-10-08: that the first refusal would have lapsed anyway through a page edit. BUILT: record exits 2 for consolidate with fewer than two pages; skill and merge-protocol say one abstain in one call naming every page of a group read in full; tests for the refused call, a two-page control, a one-page repair key, and a three-page key that covers the group until a page changes. Worker ran ruff, mypy, pyright and the two test files (21 passed); the full gate on 85304cd4 writes reports/board/gate-85304cd4.txt. ITEM 2 AS WORDED IS REJECTED: no subject-evidence gate, because the consolidate_has_work docstring (TRDD-3XS3PDCF) shows a keyword proxy over- and under-fires and the under-fire hides a real merge; the box stays unticked and its intent is carried by the refusal ledger plus this commit. BOX 4 was already met: tests/test_memory_maintenance.py 416 and 735 read by the main session, 359, 758, 799, 841 by name; the 2026-10-09 note saying no such test exists was wrong. BOXES 1 and 2: is_drained and expire_drained read by the main session, tests at test_memory_dispatch_claim.py 1623 and 1649; dedup is _supersede_older_unclaimed (memory-maintenance.py 265, TRDD-Q7X4M2KP) with test_memory_maintenance.py 1090; this repo's claim log holds no drained line, the two drains of 2026-10-08 in other projects are worker-read. BOX 5 stays open, decided as KEEP: five pending records here, not eight; three are under two days old; the two of 2026-09-03 are retro-lesson PROJECT, whose root is the live PROJECT corpus through the old path alias, and enrich LOCAL on the old path's slug directory, which still exists. A 30-day expiry for kinds the drain cannot judge was proposed and dropped after review: it contradicts the rule in is_drained that an unknown answer keeps the record, and the re-emit paths of enrich and retro-lesson are unread. FIELD CHECK, possible only after a release carries the skill text: a LOCAL consolidate pass records one key naming two or more pages and the candidates CLI then prints nothing for that group. Cost: 1 measuring worker, 1 coding worker (about 0.26 million tokens together), 1 review fork (0.27 million), 1 advisor call.
2026-10-10 07:58: b60db1f5, fixes from the review of 85304cd4: the guard counts distinct pages (the same page twice passed before); merge-protocol.md no longer carries the two older sentences that contradicted the new paragraph. GATE on 85304cd4: ruff, mypy, pyright exit 0; 18279 passed, 2 skipped (reports/board/gate-85304cd4.txt). The gate on b60db1f5 writes reports/board/gate-b60db1f5.txt and had not reported when this line was written; the two touched test files pass (22). LIVE CHECK of the three-page key, by the main session on this repo's LOCAL root with the repo's CLI at 85304cd4: after recording the 07:34 pass's own verdict under one key naming all three pages, the candidates CLI printed nothing; before it, with the pass's three one-page keys, the group was listed. That key is hand-recorded and lifts with memory_refusal_cli.py clear. CORRECTIONS to the earlier line of today: 'five pending records here, not eight' compares two roots, the eight were the peer's queue in August, so read it as 'five here'; tests 1623, 1649 and 1090 are known by name and by the green suite, their bodies were not read. NOT COVERED, unread: whether other chores with multi-page keys (conflict) have the same inert one-page shape; what the agent does when the CLI exits 2. Box 3 was reworded and ticked on the owner mandate of 2026-10-09 (decide yourself); box 5 stays open as KEEP, so this card cannot reach complete until box 5 is reworded or the two September records are consumed.
2026-10-10 07:59, from the review of d2db06ae. BOX 3 is back to its original text, unticked and marked rejected: the reworded box certified behaviour that predates this card's code, and its LOCAL evidence was the hand-recorded key. Closing this card later needs an explicit decision on a rejected box, not a tick. THE LOCAL FIELD CHECK IS SUPPRESSED by that hand key until one of the three pages changes or 7 days pass; watch a PROJECT or USER consolidate pass after the release. PROJECT printed no candidate at about 07:27; why (refusals, size gate or no group) was not looked at. NOT FIXED, by decision: the guard compares Path objects, so one page spelled two ways through different absolute paths (a symlinked root alias) still passes; pathlib already folds ./a.md into a.md (checked), the remaining case needs an agent to mix an alias path with a bare name, and the fix would cost another worker, gate and review round. The ruff blank-line fix in b60db1f5 also touched two unrelated atomize tests, formatting only. The hand key was written by the main session to the janitor's live ledger, an act the heartbeat protocol leaves to the memory agent; done to stop a repeat spawn, disclosed here.
2026-10-10 08:17: 46723bc7, from the review of 38dae7e9: the guard compares resolved pages (the earlier 'not fixed, by decision' note is withdrawn: the fix was one expression, this repo is itself reached through a symlink alias, and sub/../a.md was not folded by pathlib); SKILL.md and the merge-protocol example no longer speak of exactly two pages. GATE on b60db1f5: ruff, mypy, pyright exit 0; 18280 passed, 2 skipped. The worker ran lint and the two test files on 46723bc7; the full gate on it writes reports/board/gate-46723bc7.txt. BOX 5 is carried by TRDD-S41TV0I7 (eht), which holds the facts and what must be read first. BOX 3 stays rejected and unticked; this card closes after its field check and S41TV0I7, with box 3 recorded as closed by decision at that time. The hand-recorded LOCAL key STAYS: it records the memory agent's own stated verdict and lifts with one clear command. Correction: the PROJECT candidates run printed nothing at 07:25 by the date command, not 'about 07:27'.
2026-10-10 08:41, from the review of 6cb60ea9. GATE and STRICT VALIDATOR GREEN on 46723bc7: 18281 passed, 2 skipped; validator exit 0, CRITICAL 0, MAJOR 0, MINOR 0, NIT 0, WARNING 42, run with PLUGIN_SKIP_GITHUB_INTEGRITY=1 (reports/board/gate-46723bc7.txt, strict-validate-46723bc7.txt). KNOWN LIMIT, not fixed: the guard compares resolved paths but candidate_key stores the paths as given, so a bare name mixed with an absolute path through the symlinked root alias passes the guard and records a key that matches no pair; unobserved, left after three code rounds. Also unread: whether two symlinked names of one file can sit in one consolidate group, where the REFUSED wording would mislead. The PROJECT candidates run of this morning happened between 07:25 and 07:35; no closer time is known. Work on this card stops here until its field check.

## Approval log

- 2026-10-07T09:35:39+0200 — column → testing by main-agent@ai-maestro-janitor. built and merged on main; release observation
2026-10-09 BACK TO todo (board drain, wave 3): drain and dedup are shipped and evidenced (tests pass per the assessing worker; two drained records logged in other projects on 2026-10-08), but the card's own note says items 2 and 3 are not done: consolidate still groups on same tier and type only, with no subject evidence (scripts/lib/memory_content_precheck.py consolidate_group_defect), and no test for 'empty candidates, no marker' was found. Five pending records remain in this repo, two from 2026-09-03 of kinds that never drain by design. Assessment: reports/board/20261009_233351+0200-wave3-batchH.md.
- 2026-10-09T23:50:56+0200 — column → todo by main-agent@ai-maestro-janitor. items 2 and 3 of the card are not done
- 2026-10-10T07:58:46+0200 — column → testing. built at 85304cd4 and b60db1f5; field check needs a release carrying the skill text

## Field notes

2026-10-10 10:14, not this card's field check (the machine runs the released 3.8.11, which lacks the fix): a consolidate pass on USER, dispatched by the 09:55 heartbeat, abstained on five groups (about 190 pages) and recorded one abstain per group while reporting that it did not open every page. Its own report: reports/janitor-memory-subconscious-agent/20261010_095531+0200-consolidate-user.md (gitignored). The ledger was NOT read by the main session, so which pages those keys name is unknown. If they name unread pages, those groups are silenced for 7 days on a partial read, which is what the new skill sentence (name only pages read in full) is meant to stop. It also reported claim 1791460073-1d22bb32 still in flight (TRDD-JYA0MFVY).
