---
trdd-id: HL8H3XCV
title: token-usage-anomaly — cross-check the learned baseline against agentlensPro burn status
column: complete
created: 2026-07-11T12:35:46+0200
updated: 2026-07-12T05:04:10+0200
current-owner: janitor-claude
assignee: null
priority: 4
severity: LOW
effort: S
labels: [agentlens, detector, tokens, anomaly]
task-type: refactor
parent-trdd: TRDD-WUUR2DFX
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
impacts: []
attempts: 0
test-failures: 0
last-test-result: pass
last-test-at: 2026-07-12T05:04:10+0200
implementation-commits: [f18e233, e2e4e89]
external-refs: []
---

# token-usage-anomaly — corroborate the local baseline with agentlensPro

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body)

**Status: COMPLETE — shipped on `main` (commit f18e233), unpushed, awaiting the
NON-EXEMPT publish approval.** 45 tests green (`tests/test_token_usage_anomaly_detector.py`,
incl. 3 new real-subprocess cross-check tests), ruff clean. Shared probe lib
`scripts/lib/agentlens_probe.py` (commit e2e4e89, TRDD-WUUR2DFX).

**What SHIPPED — CROSS-CHECK (corroborate + attribute), NEVER suppress.** `_agentlens_enrich()`
runs ONLY after the local median+MAD baseline (`token_baseline.classify_recent`, PURE +
untouched) has already decided to alarm, and appends to the drift line: the real
machine-wide burn RATE (`get_burn_status.global.costPerHour`) and the top culprit CAUSE
(`investigate_burn`). Config: **`heartbeat_burn_status_command`** + **`heartbeat_investigate_burn_command`**
(defaults `agentlenspro get_burn_status` / `investigate_burn`; empty disables each).
Fail-open — a missing CLI leaves the alarm byte-identical to before.

**CORRECTION — proposal item 2 ("Suppress or downgrade a local spike the account-level
view contradicts") is a DELIBERATE NON-GOAL and did NOT ship (decision 2026-07-12).** The
local baseline is authoritative for the detector's actual job — "this SESSION's own
heartbeat cost spiked" — so downgrading a real local signal on an account-level view would
HIDE a real spike (a false negative on the very thing the detector exists to catch).
agentlensPro therefore CORROBORATES and ATTRIBUTES only; it never gates the local alarm.
Items 1 (raise confidence when both agree) + 3 (attribute via `investigate_burn`) shipped.

**SUPERSEDED — do NOT carry forward:** "Why this is a cross-check" item 2 (suppress/
downgrade) below — never implemented, by design.

## Problem

`scripts/detectors/token-usage-anomaly.py` (TRDD-EDSFEQ5C) learns a robust per-5-min
baseline (median + MAD — never a mean; the log is heavy-tailed and bursty) from the
janitor's own `token-meter.jsonl`, and alarms on a SUDDEN outlier. It is the SLOW
pattern signal complementing the FAST per-turn `pre-tool-token-budget` guard.

Its weakness is not the math — it is the **horizon**: it only sees THIS project's
meter. agentlensPro's `get_burn_status` / `investigate_burn` see the whole account, and
`investigate_burn` can attribute a spike to a cause.

## Why this is a cross-check, not a switch

The local baseline answers *"is this session behaving abnormally FOR ITSELF"*;
`get_burn_status` answers *"is the ACCOUNT burning fast"*. They are different
questions, and the local one is the detector's actual job. So the CLI should not
replace the baseline — it should:

1. **Raise confidence / severity** when both agree (local spike AND account-level burn
   → this session is very likely the culprit; the drift line can say so).
2. **Suppress or downgrade** a local spike the account-level view contradicts (a
   one-bucket blip while the account is calm is noise, not an incident).
3. **Attribute** — call `investigate_burn` only AFTER the local detector has already
   decided to alarm, and paste its one-line cause into the drift line. Never call it
   speculatively (it is the expensive probe).

The existing fleet-attribution path (`token_history.fleet_attribution` /
`culprit`, 30-min machine-wide cache) already does a native version of (3); the CLI
should be preferred over it when present, with that code staying as the fallback.

## Proposed change

- New config option `heartbeat_burn_status_command` (default
  `agentlenspro get_burn_status`; empty disables).
- The detector's PURE decision layer (`token_baseline.classify_recent`) is untouched —
  the CLI's verdict is folded in AFTER it, as a confidence/severity modifier, so the
  existing pure tests keep guarding the math.
- `investigate_burn` is invoked at most once per alarm, bounded + cached, never on the
  quiet path.

## Verification

- Unit: real-subprocess probe parse; probe-absent ⇒ today's behavior byte-for-byte;
  agree ⇒ severity up; contradict ⇒ downgraded/suppressed; `investigate_burn` is NOT
  invoked on a quiet fire (assert zero subprocess spawns).

## Approval log
