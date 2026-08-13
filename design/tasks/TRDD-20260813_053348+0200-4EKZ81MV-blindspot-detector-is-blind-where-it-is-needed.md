---
trdd-id: 4EKZ81MV
title: The cross-card blindspot detector is weakest exactly where it is most needed
column: todo
created: 2026-08-13T05:33:48+0200
updated: 2026-08-13T06:02:40+0200
current-owner: janitor-main-session
task-type: bugfix
approval-tier: 0
scope: project
severity: medium
relevant-rules: []
npt: []
eht: []
external-refs: [TRDD-XFPOAF2I]
---

# The blindspot detector cannot see the cards it exists to find

`scripts/detectors/trdd-cross-card-blindspot.py` (shipped `20a1c14e`, self-corrected
`c4f11738`, card TRDD-XFPOAF2I — now `complete`, so this is a follow-on card rather than an
edit to a terminal one) groups open cards by a **shared `external-refs:` value** and reports
pairs. That is its whole detection surface, and it contains a structural contradiction:

> **Two cards are blind to each other precisely when neither knows the other exists — and a
> card that does not know another card exists has no reason to have cited the same issue.**

So the detector fires on cards that ALREADY share a citation — which is close to the
definition of *not blind* — and stays silent on the genuinely blind ones. Its coverage is
inverted with respect to its purpose.

## Evidence — two confirmed instances, both found BY HAND, both invisible to the detector

1. **TRDD-JPL0JU86 ⇄ TRDD-AZ6QRK0D** (found 2026-08-12). Same symlink mechanism from opposite
   ends; one calls it the wrong mechanism, the other generalises it. They shared no
   `external-refs:`. JPL0JU86 records this explicitly: *"the two share no `external-refs:`, so
   `trdd-cross-card-blindspot` could not see them."*
2. **The iTerm-alarm trio — 9PDH8G0W ⇄ EZ3PMQYX ⇄ KU3ERYFX** (measured 2026-08-13). All three
   are about the same alarm. Their refs:

   | card | `external-refs:` |
   |---|---|
   | 9PDH8G0W | *(absent entirely)* |
   | EZ3PMQYX | `[janitor#92, janitor#233, janitor#235, janitor#236, janitor#237, TRDD-88ZVEQY7]` |
   | KU3ERYFX | `[janitor#234]` |

   Zero overlap, and one card has no refs at all — so no amount of dedupe tuning changes the
   outcome.

### ⚠ CORRECTION 2026-08-13 — one piece of the evidence above was CONFOUNDED

This card originally added: *"A run today emitted nothing, and no
`trdd-cross-card-blindspot-seen.txt` exists."* **Withdraw the seen-file half.** The detector was
committed at `20a1c14e` with git mode `100644`, and `_run_detector` skips any script failing
`os.access(..., X_OK)` — so it had **never run from the heartbeat at all**. An absent seen-file is
exactly what that produces, independently of recall. Fixed in `30d9ddc1`.

My "a run today emitted nothing" was a HAND run via `uv run --script <path>`, an
explicit-interpreter invocation that is mode-agnostic — the same blind spot
`tests/test_detector_executable_bits.py` was written to close. The manual run succeeding and the
production path skipping it entirely are perfectly consistent observations, which is why nothing
looked wrong.

**The card's thesis is unaffected**, because it never rested on that half: the zero-overlap table
above is a property of the CARDS, not of any run. Two cards that share no `external-refs` cannot be
paired by a detector that groups on shared `external-refs`, whether or not it ever executes. That
remains true and remains the whole argument.

Correcting rather than deleting, because the mistake is the reusable part: **an untested
verification path can make a real defect and a never-executed guard produce identical evidence.**

**Sample so far: every real relationship on this board was found by a human reading, none by
the detector.** That is a small sample and the detector is young — but it is the only sample
there is, and it points the same way twice.

## The honest framing

The `c4f11738` fix (a shared `TRDD-<id8>` ref is structure, not blindness — it was
manufacturing false positives from its own remedy) was correct and made the detector
*sound*. This card is about the other half: soundness bought at the cost of nearly all
recall. A detector that is silent on both known instances is not yet earning its roster slot,
and its silence currently reads as "the board is clean".

## What (options — this needs a decision, not a reflex)

Ranked by how much they attack the actual inversion rather than widening the same surface:

1. **Content similarity over titles + STATE blocks** — the two instances share vocabulary
   (`symlink`/`USER scope`; `iTerm`/`Automation`/`grant`) while sharing no refs. Cheap, no
   frontmatter discipline required, and it keys on what actually makes two cards duplicates.
   Risk: false positives on shared house vocabulary — needs the same falsification bar the
   `c4f11738` fix got.
2. **Shared touched-FILES** — cards naming the same `scripts/…` path in their Files/STATE
   sections. Precise where it applies; silent for design-only cards (the iTerm trio is mostly
   design prose, so this alone would still have missed it).
3. **Accept the narrow surface and say so** — keep refs-only, but have the detector state its
   own coverage where a reader sees it, so silence stops reading as "clean". Weakest fix, but
   strictly better than an unstated limit.

Do NOT simply loosen the `_BARE_OR_PREFIXED_TRDD_RE` exclusion to regain recall — that is the
exact non-convergence `c4f11738` closed (the detector's own recommended remedy adds a shared
TRDD-ref, which would then re-trigger it forever).

## Acceptance

- [ ] The detector reports the JPL0JU86 ⇄ AZ6QRK0D pair from the state both cards had BEFORE
      they were cross-linked on 2026-08-12 (the cross-link is now in the tree, so the fixture
      must reconstruct the pre-link frontmatter — testing against today's files would pass
      for the wrong reason)
- [ ] The detector reports at least one pair from the iTerm trio, INCLUDING the card that
      carries no `external-refs:` at all
- [ ] Falsified per-guard: each new signal proven by breaking it and watching a test go red
- [ ] No regression in soundness — the `c4f11738` shared-TRDD-ref case still does NOT fire,
      and a full board run does not manufacture pairs from shared house vocabulary

## Notes and lessons learned
