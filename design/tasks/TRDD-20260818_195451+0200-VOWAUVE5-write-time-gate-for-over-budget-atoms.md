---
trdd-id: VOWAUVE5
title: memgrep write verbs refuse an over-budget atom at write time
column: testing
created: 2026-08-18T19:54:51+0200
updated: 2026-08-21T08:30:42+0200
current-owner: janitor-main-session
task-type: feature
approval-tier: 0
scope: project
created-by: TRDD-WN7M829Y
relevant-rules: []
npt: []
eht: []
external-refs: [janitor#200, TRDD-3K8SVX2H]
---

# memgrep write verbs refuse an over-budget atom at write time

## Why

TRDD-WN7M829Y measured four times, over three weeks, that the `atom-oversized` backlog never
converges: nothing prevents creation, the finding tier is INFO (ratified in janitor#200 — a
style debt, so no automation may act on it), and the only drain is a hand-dispatched agent
batch nobody schedules. The closed loop is the card's final finding: every "how many oversized
atoms remain" measurement is just a proxy for "how long since someone ran a batch".

Decision (2026-08-18, under the USER's delegation, recorded on WN7M829Y): stop the INFLOW at
the source — the write verbs refuse an over-budget body — rather than raising the tier
(quietly reverses ratified #200) or accepting permanent debt (re-measured forever). WN7M829Y's
own analysis: a write-time gate generalises where a per-class repair batch must re-run forever.
This mirrors the engine's existing philosophy: `normalize_page_until_clean` already brackets
every `atomic_write_page` because "a write that skipped normalization would persist a
malformed page" — an over-budget atom is the same class of malformation, caught earlier.

## What

1. `memgrep add-atom` / `add-lesson` reject a body over the atom budget (the same bound
   `memgrep lint` uses for `atom-oversized`) with a clear refusal telling the author to split
   the fact — exit non-zero, nothing written. One budget constant, shared with the linter:
   never a second threshold to drift.
2. Carve-out per TRDD-3K8SVX2H: bodies under `## Superseded` are protocol-frozen and must be
   netted OUT of any backlog metric; the gate applies to NEW writes only and never blocks a
   supersession that carries an existing oversized body forward verbatim.
3. Migration note: the residual stock (last measured 15 PROJECT+USER atoms, 2026-08-16) is
   drained by ONE final hand-dispatched batch after the gate lands; with inflow stopped the
   count then stays at zero instead of refilling.
4. Tests: over-budget add-atom refused (nothing written, exit != 0); at-budget accepted;
   supersession carrying an oversized legacy body verbatim NOT blocked; budget constant
   asserted identical between gate and linter.

## Acceptance

- [x] `add-atom`/`add-lesson` refuse an over-budget body; no partial write; message names the
      split skill — `check_new_body_budget` called on the stdin body BEFORE the write gate and
      any page read (refuse cheap and early); BEHAVIORALLY verified through the bare installed
      `memgrep` (1600-char body → the refusal, exit non-zero, nothing written). The lesson verb
      gates the COLLAPSED one-line text, i.e. what actually lands on the page.
- [x] gate and `atom-oversized` linter share ONE budget constant — both call the same
      `atom_max_chars()` (env `MEMGREP_ATOM_MAX_CHARS`, 0 disables both identically); the
      gate's raw-chars measure is stricter-or-equal to the lint's whitespace-joined
      `body_chars`, so nothing the gate admits can lint oversized.
- [x] supersession carve-out proven by test — `supersession_moves_an_oversized_body_without_
      regating_it` pins that `--supersedes` relocates the existing oversized body verbatim
      without it ever passing the gate; only the NEW body is measured. 5 new crate tests,
      145/145 green.
- [ ] after one drain batch, `memgrep lint` atom-oversized (net of the 3K8SVX2H frozen class)
      is 0 and stays 0 across a week of heartbeats — HALF DONE: the drain batch ran
      2026-08-19 (janitor-memory-subconscious-agent, direct dispatch): 4 PROJECT atoms
      decomposed into 12, LOCAL/USER already clean, re-lint across all 3 scope roots =
      **0 atom-oversized anywhere** (commit `5c9684bd`; report
      `reports/janitor-memory-subconscious-agent/20260819_000527+0200-vowauve5-drain-batch.md`).
      Remaining: the week-long stays-at-zero observation — window 2026-08-19 → 2026-08-26.
      The gate is live on THIS host now (`cargo install` done); other hosts get it via the
      release.

## ⏵ STATE — 2026-08-21: **THE STAYS-AT-ZERO HOLD HAS ALREADY REGRESSED, and the gate cannot prevent it**

Re-measured mid-window (day 2 of 7). `atom-oversized` across the three scope roots:
PROJECT **0**, LOCAL **0**, USER **1**.

The one:

```text
INFO …/memory/repair-reflags-correct-page-tier-shape.md:15 [atom-oversized]
     — atom body is 1733 chars (> 1500)
```

`^ATOM-J8YH-IK0E`, `ocd: 2026-08-20` — **created the day AFTER the gate shipped and after the
drain batch**, on the host where `cargo install` had already been done. So this is not drain
residue and not the `3K8SVX2H` frozen class; it is a fresh over-budget atom written past a live
gate.

**Root cause, and it is a coverage hole rather than a bug in the gate:**
`check_new_body_budget` has exactly TWO call sites in the whole crate —
`memory.rs:2721` (`add-atom`) and `memory.rs:3107` (`add-lesson`). Every other way a page
legitimately gets written is ungated: the `migrate` and `edit` verbs, and — the one that matters
most — **an agent editing the markdown directly with the Edit tool, which the memory protocol
explicitly permits** ("edit pages ONLY via memgrep verbs *or the Edit tool*").

So acceptance box 4 is not defended by the thing that was built to defend it. A write-time gate
inside the crate cannot bind a writer that does not go through the crate, and the protocol hands
every agent exactly such a path. The box asks for an outcome (`stays 0`) that the mechanism can
only influence, not enforce — which is why it regressed within two days without anyone doing
anything wrong.

*(Confirmed the gate itself is healthy and NOT the leak: it refused two of my own atoms today at
2036 and 1572 chars, in ordinary use, through the installed binary. And the offending atom is
not mine — the gate-vs-lint invariant in box 2 held for every write I made.)*

**NEXT ACTION — a decision, not a patch.** Three options, and the cheap one is wrong:
1. *Gate `migrate`/`edit` too* — closes two holes, leaves the Edit-tool hole open, and risks
   refusing a legitimate migration of large legacy content (the reason box 3's supersession
   carve-out exists).
2. *Re-scope box 4 to what a gate can actually promise*: "no VERB-written atom is over budget"
   (enforceable, provable) plus "the linter reports the rest", instead of a fleet-wide
   stays-at-zero that no single writer controls.
3. *Make the linter's finding actionable on a schedule* — the drain chore re-runs and decomposes
   what any path introduced, accepting that the steady state is "small and repaired", not zero.
**Option 2 + 3 together is the recommendation**; option 1 alone would let the box keep claiming
an enforcement it still would not have. Needs the USER, because it changes what this card
promises.

## Approval log
