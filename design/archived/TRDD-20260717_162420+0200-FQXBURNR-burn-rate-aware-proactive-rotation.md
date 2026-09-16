---
trdd-id: FQXBURNR
title: Burn-rate-aware proactive oauth rotation — rotate on projected exhaustion, learn the effective cap
column: complete
created: 2026-07-17T16:24:20+0200
updated: 2026-08-05T18:05:00+0200
implementation-commits: [2f32dbc2]
current-owner: claude-ai-maestro-janitor
task-type: feature
scope: project
severity: high
parent-trdd: H7NVKSAX
created-by: H7NVKSAX
related-trdd: [32ACD15F, EDSFEQ5C]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-17

**Gap (from the TRDD-H7NVKSAX incident):** the proactive rotator (`cmd_auto` /
`is_near_limit`) gates on a UTILIZATION THRESHOLD alone. On 2026-07-17 the live account
read "5h=61–63% — within limits" every minute right up to a hard 429; the rotated-to
account then burned 6%/min (42→61% in 3 min). A pure threshold cannot see either failure
mode: (a) fast burn — the wall arrives minutes after a below-threshold reading; (b) an
EFFECTIVE cap below 100% — real 429s land while the usage endpoint still reads ~60%.

**Design (reuse the existing pure math — no new telemetry):**
1. **Projected exhaustion**: keep the last N per-tick `(ts, util%)` samples per account in
   the rotator state; slope → minutes-to-wall. Rotate when projected exhaustion of the
   LIVE account < `ROTATE_HORIZON_MIN` (default ~15 min) AND a safe alternate exists —
   even below the util threshold. `token_baseline.projected_exhaustion_epoch` /
   `burn_ratio` already implement the math; keep the new glue PURE + tested.
2. **Learned effective cap**: on a REAL rate-limit 429 (the 429×2 reactive trigger), record
   the last known util% for that (account, window) as an observed cap sample; the
   near-limit bar for that account becomes `min(configured_threshold, learned_cap − margin)`.
   TRDD-EDSFEQ5C's window-exhaustion empirical-cap machinery is the precedent — reuse its
   shape, do not duplicate it.
3. Alternate SELECTION should also consider the candidates' own burn slope (don't rotate
   into an account that will wall in 10 min), composing with the existing drain-first
   policy (user decision 2026-05-29 — unchanged).

**Constraints:** R16 untouched (read-only usage probes; no token-handling changes);
fail-open — no samples / flat slope ⇒ today's threshold behavior, byte-for-byte.

### ✅ 2026-08-02 18:58 — IMPLEMENTED. Column `testing` — awaiting one real burn-triggered rotation.

**Shipped:** `scripts/oauth_rotator/burn_gate.py` (pure, no I/O, no keychain — R16 untouched)
+ 4 minimal `cmd_auto` wiring points + 16 tests:

1. **Projected exhaustion** — per-(account, window) bounded sample ring in `state.json`
   (`usage_samples`, ring-capped 12), least-squares slope over FRESH samples (≥3, ≥2 min
   span, ≤30 min old), `minutes_to_wall` vs the LEARNED cap when one exists; the live
   account rotates when the wall is inside ROTATOR_ROTATE_HORIZON_MIN (15) even below the
   threshold. The incident shape (6%/min at 61%) projects ~6.5 min and trips; the same ring
   spanning a window reset yields a declining slope → None → fail-open.
2. **Learned effective cap** — a DEBOUNCED live 429 records the ring's freshest util% into
   `learned_caps` (capped 5); the near bar becomes min(configured, min(caps) − 5), floored
   at 50% so one absurd sample cannot spin every tick into a rotation. A later steady 61%
   under a learned 63% cap rotates (tested) — the "429 at 61% while /usage reads fine" case.
3. **Selection** — alternates' probes feed their own rings; a candidate whose OWN wall
   projects inside the horizon is filtered with a `walls-soon` verdict. Drain-first is
   UNCHANGED (filter only, never re-order). Sparse history ⇒ never filtered (fail-open).
4. **Fail-open contract pinned by tests**: empty/corrupt state, <3 samples, flat/declining
   slope, stale samples, no caps — every path returns neutral and the pure-threshold
   behavior stands. Full rotator/oauth cluster: 463 green.

**NEXT ACTION (testing):** observe ONE real `+BURN[...]` rotation (or a `walls-soon`
candidate filter) in `_decide`'s log on this host, then `complete`. Knobs are plain
ROTATOR_* envs like their siblings (HORIZON_MIN / CAP_MARGIN / SAMPLE_KEEP / CAP_KEEP /
SAMPLE_MAX_AGE_S / EFFECTIVE_FLOOR_PCT).

## Notes and lessons learned

[^1]: [id:ATOM-BURN-HRZN, status:valid, keywords:"usage percent said within limits then 429 minutes later fast burn threshold too slow rotate too late", ocd:2026-07-17, lmd:2026-07-17]
  DO NOT gate proactive rotation on a utilization threshold alone, BECAUSE a fast-burning
  window walls minutes after a below-threshold reading and an effective cap can sit well
  under 100%. DO rotate on projected minutes-to-wall and learn the cap from observed 429s.
