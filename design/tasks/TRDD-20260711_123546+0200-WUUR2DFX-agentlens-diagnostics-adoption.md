---
trdd-id: WUUR2DFX
title: Adopt agentlensPro as the janitor's authoritative diagnostics source — retire the home-grown estimates
column: backburner
created: 2026-07-11T12:35:46+0200
updated: 2026-07-12T05:04:10+0200
current-owner: janitor-claude
assignee: null
priority: 3
severity: MEDIUM
effort: M
labels: [agentlens, diagnostics, tokens, observability]
task-type: refactor
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
test-requirements: [unit, lint]
review-requirements: []
runtime-targets: [macos, linux]
impacts: [config-schema]
attempts: 0
test-failures: 0
last-test-result: pass
last-test-at: 2026-07-12T05:04:10+0200
implementation-commits: [e2e4e89]
external-refs: ["github.com/Emasoft/ai-maestro-janitor/issues/78", "github.com/Emasoft/ai-maestro-janitor/issues/83"]
---

# Adopt agentlensPro as the janitor's authoritative diagnostics source

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body)

**Status: BACKBURNER — the umbrella task; its two named detector children have SHIPPED.**
User steer (2026-07-11, verbatim): *"examine the agentlens skill and learn how to use the
cli diagnostic tool, much better than the current janitor estimations on token usage or
about what account type is running, or similar things."*

This is the PARENT of two concrete detector adoptions, each its own TRDD — **BOTH now
COMPLETE (shipped on `main`, unpushed, awaiting the NON-EXEMPT publish approval):**
- **TRDD-90B47EM9** — `window-burn-rate`: ENRICH the culprit clause with `investigate_burn`
  cause; KEEP the rotator `/api/oauth/usage` window% (commit e107a57).
- **TRDD-HL8H3XCV** — `token-usage-anomaly`: CROSS-CHECK — corroborate (`get_burn_status`
  burn rate) + attribute (`investigate_burn` cause) after the local alarm, NEVER suppress
  (commit f18e233).

The shared config-gated / bounded / fail-open probe substrate is
**`scripts/lib/agentlens_probe.py`** (commit e2e4e89, 24 tests) — the reference shape both
children copy, mirroring the earlier TTL-regime probe in `scripts/lib/heartbeat_cadence.py`
(TRDD-0QQX9H0G). Do not invent a second integration shape.

**THE OPEN QUESTION IS ANSWERED (below) — switch vs cross-check resolved by live-CLI
verification (2026-07-12): a per-detector SPLIT, driven by what agentlensPro actually
measures.**

**REMAINING (optional, not started):** the last two inventory rows — `token_report` /
`token_baseline.estimate_window_cap` absolute-cap inference, and plan/account-type in
reports. Both would consume `get_account_status`; neither is scheduled. NOT blocking.

## The invariant every adoption MUST hold

agentlensPro is a **machine-local, optional** tool. The janitor NEVER hard-depends on
it. Every call is:

1. **Config-gated** — a `heartbeat_*_command` option whose empty value disables the
   probe entirely (precedent: `heartbeat_cost_command` from #78,
   `heartbeat_account_status_command` from #83).
2. **Bounded** — short subprocess timeout (5 s), result cached, never on a hot path.
3. **Fail-open** — missing binary / non-zero exit / timeout / unparseable output ⇒
   fall back to the janitor's own native estimate, silently. A diagnostics tool being
   absent must never degrade the heartbeat.
4. **Prefer-when-present** — when the probe answers, its answer WINS over the native
   estimate (that is the whole point: the CLI reads the real account state; the janitor
   was guessing).

## Inventory — where the janitor currently guesses

| Janitor surface | Guesses | agentlensPro authority |
|---|---|---|
| `heartbeat_cadence.resolve_ttl_minutes` | env heuristic (`ANTHROPIC_API_KEY` ⇒ 5 else 60) — WRONG for an over-plan subscription drawing usage credits (drops to a 5-min TTL with no API key) | `get_account_status` → `cacheTtl {minutes, regime, ttlSource}` — **DONE (TRDD-0QQX9H0G)** |
| `window-burn-rate` detector | window utilization/reset from the OAuth rotator's own probe (STAYS — agentlensPro has NO authoritative window budget) | culprit/cause via `investigate_burn` — **DONE (TRDD-90B47EM9)** |
| `token-usage-anomaly` detector | median+MAD baseline over the janitor's own `token-meter.jsonl` (STAYS PRIMARY, never suppressed) | corroborate burn rate + attribute cause — **DONE (TRDD-HL8H3XCV)** |
| `token_report` / `token_baseline.estimate_window_cap` | infers the absolute window cap from a utilization% sample | the CLI reports the real budget directly |
| plan / account type in reports | inferred | `get_account_status` → plan name |

## Open question — ANSWERED (2026-07-12, live-CLI verification + USER decision)

**Original question:** do the two detectors *switch to* agentlensPro, or *cross-check* it?

**Answer: a SPLIT, decided by what agentlensPro actually measures.** The live CLI (verified
2026-07-12) observes spend via OTEL, NOT Anthropic's `/api/oauth/usage` — so with no
configured capacity it reports `capacitySource: "none"` and its window budget / % /
projection are null. agentlensPro is therefore authoritative ONLY for realtime burn RATE
(`get_burn_status.global.costPerHour`) and CULPRIT/CAUSE attribution
(`investigate_burn.findings`), NOT window utilization%. That kills the naive "switch the
window budget" plan and yields the per-detector split the USER approved ("Anomaly switch +
burn enrich"):

- **window-burn-rate → ENRICH.** The rotator's `/api/oauth/usage` read STAYS authoritative
  for window% (the only authoritative window% source); only the CULPRIT clause is switched
  to `investigate_burn`, with the native fleet-scan as fallback. (TRDD-90B47EM9, shipped.)
- **token-usage-anomaly → CROSS-CHECK.** The local median+MAD baseline stays PRIMARY and is
  NEVER suppressed (suppressing it would hide a real per-session spike); agentlensPro
  CORROBORATES (burn rate) + ATTRIBUTES (cause) after the local alarm. (TRDD-HL8H3XCV, shipped.)

Both hold the umbrella invariant: config-gated, bounded, fail-open, prefer-when-present —
so a machine without agentlensPro is byte-identical to before.

## Approval log
