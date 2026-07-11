---
trdd-id: WUUR2DFX
title: Adopt agentlensPro as the janitor's authoritative diagnostics source — retire the home-grown estimates
column: backburner
created: 2026-07-11T12:35:46+0200
updated: 2026-07-11T12:35:46+0200
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
last-test-result: not-run
implementation-commits: []
external-refs: ["github.com/Emasoft/ai-maestro-janitor/issues/78", "github.com/Emasoft/ai-maestro-janitor/issues/83"]
---

# Adopt agentlensPro as the janitor's authoritative diagnostics source

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body)

**Status: BACKBURNER — the umbrella task.** User steer (2026-07-11, verbatim):
*"examine the agentlens skill and learn how to use the cli diagnostic tool, much better
than the current janitor estimations on token usage or about what account type is
running, or similar things."*

This is the PARENT of two concrete detector migrations, each its own TRDD:
- **TRDD-90B47EM9** — `window-burn-rate` → `get_window_budget` / `get_account_status.usageWindows`.
- **TRDD-HL8H3XCV** — `token-usage-anomaly` → `get_burn_status` / `investigate_burn`.

The FIRST adoption already shipped as the pattern to copy: the TTL-regime probe in
`scripts/lib/heartbeat_cadence.py` (TRDD-0QQX9H0G) — `agentlenspro get_account_status`
→ `cacheTtl.minutes`, config-gated command, 30-min cache, fail-open to a native
heuristic. Follow it exactly; do not invent a second integration shape.

**NEXT ACTION:** decide scope with the user before implementing. The inventory below is
the survey; nothing in it is committed work yet.

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
| `window-burn-rate` detector | window utilization/reset derived from the OAuth rotator's own probe | `get_window_budget` / `get_account_status.usageWindows` — **TRDD-90B47EM9** |
| `token-usage-anomaly` detector | median+MAD baseline over the janitor's own `token-meter.jsonl` | `get_burn_status` / `investigate_burn` — **TRDD-HL8H3XCV** |
| `token_report` / `token_baseline.estimate_window_cap` | infers the absolute window cap from a utilization% sample | the CLI reports the real budget directly |
| plan / account type in reports | inferred | `get_account_status` → plan name |

## Open question for the user (answer BEFORE implementing)

Do the two detectors **switch to** agentlensPro (with the native estimate as fallback),
or **cross-check** it (native primary, CLI as a corroborating second opinion that
upgrades confidence)? The switch is simpler and the CLI is authoritative; the
cross-check keeps the janitor's estimates exercised (and therefore honest) on machines
without the CLI. Recommendation: **switch, fail-open to native** — the native code path
stays alive as the fallback anyway, so it never rots.

## Approval log
