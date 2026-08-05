---
trdd-id: VXFNDHXT
title: The cache-TTL probe times out intermittently and its fallback fabricates the one value that disables the guard
column: dev
created: 2026-08-05T11:17:53+0200
updated: 2026-08-05T11:52:00+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
scope: project
severity: high
relevant-rules: []
blocked-by: []
implementation-commits: [869a0144]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body)

**PART 1 SHIPPED (`869a0144`). Parts 2 and 3 remain open, and part 2's answer depends on a
prior I have not measured — see the break-even below before implementing it.**

### 2026-08-05 — part 1 landed: a stale measurement now outranks a fresh guess

`resolve_ttl_minutes` no longer overwrites a cached reading with `_env_fallback_minutes` when
the probe fails. It reuses the last `probe`-sourced value, marked `source: "stale-probe"`,
regardless of age (`probe_interval` bounds how often we ASK, not how long an answer stays
valid). A prior `fallback` is deliberately NOT reused — reusing a guess would launder it into
something indistinguishable from a measurement.

`tests/test_ttl_stale_probe.py`, 10 tests. **Falsified:** reverting the branch fails 4 of them,
including `test_the_reused_measurement_drives_the_FAST_tier_the_guess_would_have_disabled`.

**This alone removes most of the harm**, because the intermittent-timeout case — the common one,
and the one measured on this host — now keeps its measurement instead of being overwritten every
few fires.

### CORRECTION to this card's own reasoning — I argued part 2 down using the wrong metric

The body below says flipping the fallback to the short regime would be "the wrong shape on its
own". The cost argument I used was a RATIO comparison, and a default does not pay a ratio:

| truth | run `*/5` | run `*/15` | run `*/30` |
|---|---|---|---|
| TTL=60 | 1.20P/hr (6.0x optimal) | 0.40P/hr | **0.20P/hr optimal** |
| TTL=5 | **1.20P/hr optimal** | 5.00P/hr (4.2x) | 2.50P/hr (2.1x) |

In ratio terms failing fast looks worse (6.0x vs 4.2x). In ABSOLUTE terms — what the machine
actually pays — **wrong-toward-fast costs 1.20P/hr and wrong-toward-slow costs 5.00P/hr**. The
reporter's asymmetry was right and my objection was not.

**What is still genuinely open in part 2**, and why it is not just "flip the constant": with part
1 in place, the env fallback is reached ONLY on a machine where a probe has NEVER succeeded. For
those, expected cost is `default-60: (1-p)(0.20) + p(5.00)` vs `default-5: 1.20`, break-even at
**p ≈ 0.208**. So defaulting short wins iff more than ~21% of never-probed machines are on a
short TTL (API-key sessions are already detected by env; the residual is subscription
over-plan-credits). I have not measured that share, and asserting it would be the same
unmeasured-value-wearing-the-shape-of-a-measurement error this card is about.

**NEXT ACTION:** measure (or ask the fleet for) the share of never-probed machines running a
short TTL, then settle part 2 on evidence. Part 3 (timeout budget) is independent and unstarted.

*(superseded: "Not started. Root cause is MEASURED (below); the fix is a design decision, not a
one-liner." — accurate when written, before part 1 landed.)*

Two defects, discovered together on 2026-08-05 while answering janitor#190. They compound: the
first makes the fallback fire often, the second makes the fallback harmful.

### Defect 1 — the 5s probe timeout loses a race it cannot win reliably

`heartbeat_cadence.probe_account_status(command, *, timeout=5.0)` runs
`agentlenspro get_account_status`, which makes a network call. Measured on this host, three
consecutive runs:

```
run 1: 9.18s     run 2: 6.29s     run 3: 2.89s        probe timeout = 5.00s
```

Decisive A/B through the janitor's own function:

```
timeout= 5.0s -> None   (hit the bound at 5.01s)
timeout=30.0s -> 60     (succeeded in 1.06s)
```

So the binary is present (`/opt/homebrew/bin/agentlenspro`), the command is correct, the JSON is
well-formed and carries `cacheTtl.minutes` — and the probe still fails a large fraction of the
time, purely on latency variance. Every failure is silent by design (fail-open) and lands as
`{"minutes": 60, "probed_at": …, "source": "fallback"}`.

**The 5s is not arbitrary and must not simply be raised.** Its docstring gives the reason: the
probe sits on the heartbeat path, so a hung agentlensPro must not block every fire. Raising the
bound trades one cost for another.

### Defect 2 — the fallback fabricates exactly the value that disables the guard

`_env_fallback_minutes` returns 60 for a non-API-key session. `tier_to_cron` collapses every
tier to `*/5` only when `ttl_minutes < _SLOW_TTL_MIN` (30). **So the fallback is, precisely, a
value at which the FAST-TTL guard can never trigger.** When the probe fails on a machine whose
real TTL is 5 (subscription over plan credits — the case `_env_fallback_minutes`'s own docstring
admits it cannot see), the session runs `*/15` or `*/30` with a cache that dies between fires:
every fire pays a full cold prefix WRITE (~1.25x) instead of a warm read (0.1x). The MANAGER
measured ~530k on a single such fire on a 21 MB transcript (janitor#190).

**On THIS host the bug is invisible**, because the true TTL is also 60 — the fabricated value
coincides with the measured one. That coincidence is why it survived: the state file looked
correct.

### The fix is NOT "flip the fallback to 5"

That was the ask on janitor#190 and it is the wrong shape on its own: it would put every
probe-less session on `*/5` — 12 fires/hour fleet-wide — to protect the minority whose TTL is
actually short. Being wrong toward warm is cheaper per fire but not free, and it would be wrong
on most machines.

**Preferred design — never let a fabricated value overwrite a measured one.** Three parts:

1. **On probe FAILURE, reuse the last PROBE-sourced value even when stale**, marked
   `source: "stale-probe"`, instead of substituting the env guess. A measurement from 40 minutes
   ago is strictly better evidence than a guess that ignores the account entirely.
2. **Only fall back to the env guess when NO probe has ever succeeded** on this machine — and in
   that genuinely-unknown case, fail toward the SAFE tier (short/`*/5`), per the cost asymmetry
   (wrong-toward-warm costs cheap extra fires; wrong-toward-cold costs a full prefix write each
   fire, and scales with transcript size).
3. **Separate TIMEOUT from FAILURE in the timeout budget.** Keep the fire-path bound small, but
   let a timed-out probe retry out-of-band (or raise the bound only when a cached probe value
   already exists to fall back on, so a slow probe cannot block a fire that has no answer yet).

Keep `source:` on the value whatever else changes — it is the field that made this diagnosable,
and the MANAGER's report says the same from the other side.

### Acceptance

- [x] A probe timeout does not overwrite a previously successful probe value. — `869a0144`
- [x] `source:` distinguishes `probe` / `stale-probe` / `fallback`. — `869a0144`
- [ ] With no probe ever successful, an unknown TTL resolves to the SHORT regime, not 60.
      **(part 2 — open, gated on the break-even prior in the STATE block, not on effort)**
- [x] Unit tests cover: timeout-with-cache, timeout-without-cache, first-ever-run, and that a
      `stale-probe` value still drives `tier_to_cron` correctly. — `tests/test_ttl_stale_probe.py`
- [ ] A measured before/after on a host where the probe genuinely fails — both numbers taken the
      same way (a delta needs two identical measurements).

*(superseded — do NOT carry forward: "decide part 3's shape … since parts 1-2 are settled. Then
implement with tests, and reply on janitor#190 with the result." Wrong on two counts now: part 1
is implemented rather than pending, and part 2 is NOT settled — see the STATE block, which
supersedes this line. The janitor#190 reply is posted.)*

## Context

Raised by the MANAGER on janitor#190 after measuring a ~530k cache-miss write on an idle session.
Their first ask (make the TTL a first-class term in the tier decision) was already implemented and
they withdrew it; their corrected ask is parts 2-3 above. Their framing is worth preserving:
`source: "fallback"` is *"an unmeasured value wearing the shape of a measurement"* — the same
pattern as a rule citing an enforcer that does not exist, or a version string that never changes.
