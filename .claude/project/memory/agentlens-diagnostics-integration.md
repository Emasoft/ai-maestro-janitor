---
name: agentlens-diagnostics-integration
description: "should I switch a janitor detector to agentlensPro's window budget / does agentlensPro report account window utilization% / why is agentlensPro's window budget null / capacitySource none / how do I add an agentlensPro probe to a detector / where is the agentlens_probe integration / prefer agentlensPro over the home-grown token estimates"
ocd: 2026-07-12
lmd: 2026-07-12
metadata:
  node_type: memory
  type: project
  tier: component
  globs:
    - "scripts/lib/agentlens_probe.py"
    - "scripts/detectors/window-burn-rate.py"
    - "scripts/detectors/token-usage-anomaly.py"
---

# agentlensPro diagnostics integration

The janitor consumes the optional machine-local **agentlensPro** CLI as a diagnostics
source through one shared substrate: **`scripts/lib/agentlens_probe.py`** (config-gated,
5 s-bounded, fail-open; `probe_json` → typed `parse_*` → `format_cause_clause`). Two
detectors use it, plus the TTL-regime cadence probe.

## The load-bearing verified fact (2026-07-12, live CLI)

**agentlensPro observes spend via OTEL, NOT Anthropic's `/api/oauth/usage`.** With no
configured capacity it reports `capacitySource: "none"`, so its window **budget / % /
projection are null**. It is therefore authoritative ONLY for:

- realtime **burn RATE** — `get_burn_status.global.costPerHour`, `topSessions[]`
- **culprit / CAUSE** attribution — `investigate_burn.findings[{cause, shareOfWindow,
  confidence, verdict}]` (FORK_STORM, FAT_SESSION_REWRITES, …)

It is NOT authoritative for window **utilization%** — the OAuth rotator's
`/api/oauth/usage` read stays the only authoritative window% source. This killed the
naive "switch the window budget to agentlensPro" plan (TRDD-90B47EM9's original premise).

## The per-detector split (TRDD-WUUR2DFX; USER "Anomaly switch + burn enrich")

- **`window-burn-rate` → ENRICH.** Keeps the rotator's authoritative window% math
  (`token_burn`, unchanged); only the CULPRIT clause switches to `investigate_burn`
  (`_agentlens_cause_clause()`), native `token_history` fleet-scan as fallback.
- **`token-usage-anomaly` → CROSS-CHECK.** The local median+MAD baseline
  (`token_baseline.classify_recent`) stays PRIMARY and is **NEVER suppressed** —
  downgrading a real local signal on an account-level view would HIDE a real per-session
  spike. agentlensPro only CORROBORATES (burn rate) + ATTRIBUTES (cause) AFTER the local
  alarm (`_agentlens_enrich()`).

## The invariant every probe holds

Config-gated (`heartbeat_burn_status_command` / `heartbeat_investigate_burn_command` /
`heartbeat_account_status_command` — empty string disables), bounded (short timeout,
never a hot path — the expensive `investigate_burn` runs ONLY post-alarm/post-trip),
fail-open (missing binary / non-zero / timeout / bad JSON → native fallback, silent), and
prefer-when-present. So a machine WITHOUT the CLI is byte-identical to before. Same shape
as the TTL-regime probe in `heartbeat_cadence.py` (TRDD-0QQX9H0G) — do not invent a second
integration shape.

## Governed by

- [[janitor-architecture]] — the architecture hub (owns `scripts/**`).

## Notes and lessons learned

[^1]: [ocd:2026-07-12 lmd:2026-07-12] The GOLDEN-rule verification (probe the live CLI
  before writing parsers) caught the false premise BEFORE the wrong integration was built:
  two of the three TRDDs (90B47EM9, HL8H3XCV) were written assuming a "switch" — switch
  window-burn to `get_window_budget`, and suppress a token-anomaly alarm the account view
  contradicts. Both were invalidated by ONE live-CLI probe showing `capacitySource:none`.
  Lesson: verify what an external tool actually MEASURES against its live output, not its
  command names, before designing around it.
