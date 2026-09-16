---
trdd-id: 0QQX9H0G
title: TTL-aware dynamically-tiered heartbeat cadence — stop firing 12x more often than the 1h cache TTL needs
column: published
created: 2026-07-11T11:25:47+0200
updated: 2026-07-12T03:02:07+0200
current-owner: janitor-claude
assignee: janitor-claude
priority: 1
severity: HIGH
effort: L
labels: [heartbeat, cadence, cost, cache-ttl, agentlens]
task-type: feature
parent-trdd: null
npt: []
eht: []
blocked-by: []
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
merge-strategy: squash
must-pass-tests-before-merge: true
publish-target: ai-maestro-plugins
publish-channel: stable
test-requirements: [unit, integration, lint]
review-requirements: []
runtime-targets: [macos, linux]
impacts: [config-schema]
attempts: 0
test-failures: 0
last-test-result: pass
last-test-at: 2026-07-11T12:17:00+0200
implementation-commits: [431982f, 39feb86]
published-version: 0.40.0
published-at: 2026-07-11T21:30:00+0200
external-refs: ["github.com/Emasoft/ai-maestro-janitor/issues/83", "github.com/Emasoft/ai-maestro-janitor/issues/78"]
---

# TTL-aware dynamically-tiered heartbeat cadence

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-11

**Status: PUBLISHED in v0.40.0** (commits `431982f` + `39feb86`, both in tag v0.40.0;
31 tests in `test_heartbeat_cadence.py`; `_phase_cadence_tier` wired at dispatch.py:1263).
Verified shipped 2026-07-12 — the board was mislabeled `complete` (awaiting publish) when
the code had already gone out in v0.40.0. The plan file `staged-kindling-lynx.md` is a
SUPERSEDED draft: the shipped tiers are more conservative than it proposed (FAST stayed
`*/5` to keep recovery latency identical; MID `*/15`; SLOW `*/30`), and the `_fire_fleet_stop`
esc_first follow-up it noted is also landed (daemon.py:1074 uses `injection_is_hard`).**
User-approved plan (plan file `~/.claude/plans/staged-kindling-lynx.md`). Implements
issue #83 (open); issue #78 (heartbeat-cost CLI) is already shipped (`36aeca4`) and is
the measurement tool that confirms this works.

Shipped: `scripts/lib/heartbeat_cadence.py` (pure tiers + hysteresis + cron map + the
one TTL probe helper); `dispatch._phase_cadence_tier()` at **Phase 1.5a3** (see the
placement note below); `skills/janitor-arm/SKILL.md` steps 2+6 (read `desired-cadence.cron`
/ write `armed-cadence.cron`); 8 new `plugin.json` options; 40 new tests
(`tests/test_heartbeat_cadence.py` + `tests/test_dispatch_cadence.py`). Full suite
**12,392 passed, 1 skipped; ruff clean**.

**NEXT ACTION:** rides the next release — `complete → publish` is NON-EXEMPT and needs
an explicit USER go-ahead. After it ships, verify with `agentlenspro heartbeat-cost`
that the idle per-fire series falls as sessions demote to SLOW.

**Load-bearing facts / gotchas:**
- `dispatch.py` CANNOT change its own cron (CronCreate/CronDelete are model tools). A
  dynamic cadence therefore REUSES the existing `[janitor-renew]` marker → the
  `janitor-heartbeat-protocol.md` rule runs `/janitor-arm`. Re-cadencing == re-arming.
  No new marker, no protocol-rule edit.
- The handoff is two state files: dispatcher writes `desired-cadence.cron`; `/janitor-arm`
  reads it (step 2) and writes back `armed-cadence.cron` (step 6). The dispatcher emits
  the renew marker only while `armed != desired`; it self-heals once arm reconciles.
- TTL regime is AUTHORITATIVE via `agentlenspro get_account_status` → `cacheTtl.minutes`
  (doc-matrix, verified live = 60 this machine). Fail-open, cached ~30 min, config-gated
  command — mirrors #78's contract EXACTLY (janitor never hard-depends on the local CLI).
  The env heuristic (`ANTHROPIC_API_KEY`⇒5 else 60) is only the fallback — it is WRONG for
  the over-plan-usage-credits case (auto-drops to 5-min TTL with no API key), which the
  probe gets right.
- Tier→cron (REVISED from MEASURED per-fire cost — janitor token-meter, 318 fires: a
  quiet fire on a ~510k-context session ≈ 507k cache_read ≈ $0.76): `ttl_minutes < 30`
  ⇒ all tiers `*/5` (fast-TTL, no safe slowdown, correct no-op). Else FAST=`*/5` (KEEP
  the pre-#83 cadence for active-waiting — zero recovery-latency regression), MID=`*/15`
  (3× cheaper), SLOW=`*/30` (idle, 6× cheaper). `*/30` is the safe floor: any `*/N` with
  30≤N<60 fires EXACTLY 2×/h, so the originally-planned `*/45` was no cheaper than `*/30`,
  and `*/15` for FAST would have slowed rate-limit recovery for no benefit. All overridable.
- Hysteresis: promote-to-faster immediately; demote-to-slower only after
  `heartbeat_cadence_demote_fires` (default 2) idle fires. Prevents re-arm churn.
- `heartbeat_cadence_dynamic=false` ⇒ `_phase_cadence_tier` is a total no-op; behavior is
  today's fixed cadence. Pre-existing crons re-arm to a tier on their first `[janitor-renew]`.
- **PHASE PLACEMENT (supersedes the plan's "Phase 0.6") + the DEAD-SIGNAL fix.** The
  phase runs at **Phase 1.5a3** — AFTER the rate-limit / post-compact resume
  early-returns and AFTER the keep-going nudge, but BEFORE the maintenance
  early-return. Putting it at 0.6 (as the plan said) made a recovery fire print
  `[janitor-renew]` ahead of `[janitor-resume]`, breaking the exact-output contract
  those fires have. **But moving it there silently killed two of the five FAST
  signals:** `_phase_rate_limit_recovery` and `_phase_compact_resume` each UNLINK their
  flag and `return` from `main()`, so by the time the cadence phase runs the flags are
  always gone — `rate-limited.flag` / `resume-after-compact.flag` could never read True
  in production. The unit test passed only because it calls the phase directly. A
  rate-limited unattended session would therefore have retried its resume at the idle
  SLOW cadence (every 30 min) instead of every 5 — the exact recovery regression this
  TRDD promised not to cause. FIX: both resume phases now stamp `last-resume.ts`, and
  `_cadence_active_waiting` treats a stamp younger than 30 min as ACTIVE-WAITING. That
  also closes a second hole: a session doing UNATTENDED work after a resume writes no
  user-presence breadcrumb, so it would otherwise read as idle while it works.
  Regression-guarded end-to-end by `test_rate_limit_fire_stamps_resume_then_next_fire_goes_fast`.
  Lesson: when a phase moves behind an early-return, re-verify every signal it reads is
  still *reachable* there — a signal consumed by an earlier phase is dead code that
  unit tests calling the phase in isolation will happily pass.

**Durable artifacts to read before acting:**
- `~/.claude/plans/staged-kindling-lynx.md` — the full approved plan.
- `scripts/dispatch.py` — `_phase_heartbeat_renew` (marker precedent), `main()` phase order.
- AgentlensPro `src/shared/cacheTtl.ts` (read 2026-07-11) — the doc-matrix the probe encodes.

## Problem (measured, not estimated)

The heartbeat fires a fixed `*/5 * * * *`. Every fire is a full main-conversation turn
that re-reads the whole session prefix at the 0.1x cache-read rate — ~$0.50–1.40/fire on
a large session ≈ **~$6/h just to stay warm**. But on a Claude subscription the
main-conversation prompt-cache TTL is **1 hour** (auto-requested; every fire resets it),
so `*/5` is **~12x more frequent than warmth requires**. Live evidence this session
(`agentlenspro heartbeat-cost`): a settled fire wrapping two code-review runs read
178.5M tokens = $146; issue #83's own figure: `*/5` idle ≈ $6/h, the dominant cost of a
long session.

A naive slowdown regresses the fire's OTHER duties — rate-limit auto-resume, post-compact
resume, `[janitor-renew]` before 7-day expiry, drift detection. #83 names this as a
caveat to preserve, which is why the cadence is DYNAMIC (fast when actively waiting, slow
only when idle), not a lower fixed value.

## Decision

Dynamic tiered cadence (user-approved full-#83 scope), authoritative TTL regime via
agentlensPro (auto-detect, fail-open). See the STATE block + plan file for the full
design; the tier table, signals, hysteresis, and config surface are specified there.

## Verification

- Unit (`tests/test_heartbeat_cadence.py`, no mocks): raw_tier per signal set, hysteresis
  promote-now/demote-after-N, tier_to_cron per regime + overrides, `resolve_ttl_minutes`
  probe-fresh/stale/fail-open with an injected probe.
- Dispatch integration: idle⇒SLOW; `rate-limited.flag`⇒FAST + `[janitor-renew]`;
  armed==desired⇒silent; probe=5⇒all `*/5`; `heartbeat_cadence_dynamic=false`⇒no-op.
- Full suite + `ruff check` green before commit.
- Cost proof post-ship: `.janitor/logs/heartbeat-cost.log` idle series falls as the
  cadence demotes to SLOW.

## Follow-up (separate TRDDs — AUTHORED 2026-07-11)

Broader "prefer agentlensPro over the janitor's own estimations" (user steer 2026-07-11)
is now tracked as **TRDD-WUUR2DFX** (the umbrella + the non-negotiable integration
contract), with two children: **TRDD-90B47EM9** (`window-burn-rate` →
`get_window_budget`/`get_account_status.usageWindows`) and **TRDD-HL8H3XCV**
(`token-usage-anomaly` → `get_burn_status`/`investigate_burn`). All three cite THIS
task's TTL-regime probe as the reference implementation of the fail-open
"prefer-when-present, fall back to native" pattern. Each is `backburner` and blocked on
one user decision (switch vs cross-check).

## Approval log

- 2026-07-11 — Plan approved by USER (dynamic tiered scope + auto-detect regime).
  Implementation authorized; publish (`complete → publish`) remains NON-EXEMPT and awaits
  a separate USER go-ahead.
