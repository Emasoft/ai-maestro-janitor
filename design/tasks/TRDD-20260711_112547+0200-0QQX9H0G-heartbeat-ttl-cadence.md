---
trdd-id: 0QQX9H0G
title: TTL-aware dynamically-tiered heartbeat cadence — stop firing 12x more often than the 1h cache TTL needs
column: dev
created: 2026-07-11T11:25:47+0200
updated: 2026-07-11T11:25:47+0200
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
last-test-result: not-run
last-test-at: null
implementation-commits: []
external-refs: ["github.com/Emasoft/ai-maestro-janitor/issues/83", "github.com/Emasoft/ai-maestro-janitor/issues/78"]
---

# TTL-aware dynamically-tiered heartbeat cadence

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-11

**Status: IN IMPLEMENTATION.** User-approved plan (plan file
`~/.claude/plans/staged-kindling-lynx.md`). Implements issue #83 (open); issue #78
(heartbeat-cost CLI) is already shipped (`36aeca4`) and is the measurement tool that
confirms this works.

**NEXT ACTION:** implement in this order —
1. `scripts/lib/heartbeat_cadence.py` (pure lib + one probe helper).
2. `scripts/dispatch.py` — `_phase_cadence_tier()`, called Phase 0.6 (before rate-limit
   recovery, so a rate-limited fire can still promote to FAST; runs in full+maintenance).
3. `skills/janitor-arm/SKILL.md` — step 2 reads `desired-cadence.cron` first; step 6
   writes `armed-cadence.cron`.
4. `.claude-plugin/plugin.json` — reword `heartbeat_cron`; add the 5 new options.
5. `tests/test_heartbeat_cadence.py` + dispatch integration tests; full suite + ruff green.
6. CLAUDE.md prose + repomap regen + README; commit by name. **Do NOT push** (publish
   is NON-EXEMPT — user approval).

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
- Tier→cron: `ttl_minutes < 30` ⇒ all tiers `*/5` (fast-TTL, no safe slowdown, correct
  no-op). Else FAST=`*/15`, MID=`*/30`, SLOW=`*/45` (all overridable).
- Hysteresis: promote-to-faster immediately; demote-to-slower only after
  `heartbeat_cadence_demote_fires` (default 2) idle fires. Prevents re-arm churn.
- `heartbeat_cadence_dynamic=false` ⇒ `_phase_cadence_tier` is a total no-op; behavior is
  today's fixed cadence. Pre-existing crons re-arm to a tier on their first `[janitor-renew]`.

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

## Follow-up (separate TRDDs)

Broader "prefer agentlensPro over the janitor's own estimations" (user steer 2026-07-11):
`window-burn-rate` → `get_window_budget`/`get_account_status.usageWindows`;
`token-usage-anomaly` → `get_burn_status`/`investigate_burn`. Same fail-open
"prefer-when-present, fall back to native" pattern as this task's regime probe.

## Approval log

- 2026-07-11 — Plan approved by USER (dynamic tiered scope + auto-detect regime).
  Implementation authorized; publish (`complete → publish`) remains NON-EXEMPT and awaits
  a separate USER go-ahead.
