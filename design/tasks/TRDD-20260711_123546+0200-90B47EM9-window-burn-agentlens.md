---
trdd-id: 90B47EM9
title: window-burn-rate — take the window budget from agentlensPro instead of deriving it from the rotator
column: backburner
created: 2026-07-11T12:35:46+0200
updated: 2026-07-11T12:35:46+0200
current-owner: janitor-claude
assignee: null
priority: 3
severity: MEDIUM
effort: S
labels: [agentlens, detector, tokens, burn-rate]
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
impacts: [config-schema]
attempts: 0
test-failures: 0
last-test-result: not-run
implementation-commits: []
external-refs: []
---

# window-burn-rate — authoritative window budget from agentlensPro

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body)

**Status: BACKBURNER.** Child of TRDD-WUUR2DFX (read its invariant section first — the
config-gated / bounded / fail-open / prefer-when-present contract is non-negotiable and
already has a shipped reference implementation).

**NEXT ACTION:** none until the parent's open question (switch vs cross-check) is
answered by the user.

## Problem

`scripts/detectors/window-burn-rate.py` (TRDD-OY0W6LX5) alarms when a subscription
window is heading for an early rate-limit. Today it gets its inputs from
`scripts/lib/rotator_usage.py::accounts_usage()` — the OAuth rotator's own read of
`/api/oauth/usage` — and then does its own arithmetic in `scripts/lib/token_burn.py`
(`windows_from_usage`, `burn_ratio`, `projected_exhaustion_epoch`). It also has to
*estimate* the absolute window cap from a utilization% sample
(`token_baseline.estimate_window_cap`), because the raw payload gives a percentage, not
a budget.

agentlensPro already resolves the real numbers: `get_window_budget` (and
`get_account_status.usageWindows`) report the window's actual budget, consumption, and
reset — no cap inference required.

## Proposed change

- New config option `heartbeat_window_budget_command` (default
  `agentlenspro get_window_budget`; empty string disables the probe).
- `rotator_usage.accounts_usage()` gains a preferred source: when the probe answers,
  use its windows verbatim; otherwise fall back to the current rotator-derived payload
  (unchanged code path — it stays the fallback, so it never rots).
- `token_burn.evaluate_trips` keeps its PURE signature; only the *inputs* change source,
  so the existing pure tests keep guarding the decision layer.
- Cache the probe (the burn detector runs on a 15-min cadence; one bounded subprocess
  per cadence is fine, but reuse the 30-min TTL-cache pattern if the payload proves
  stable).

## Verification

- Unit: probe parse (real subprocess scripts, no mocks — mirror
  `tests/test_heartbeat_cadence.py::test_probe_*`); probe-absent ⇒ identical behavior to
  today (the fallback path is byte-for-byte the current one); probe-present ⇒ the
  reported budget wins over the inferred cap.
- The existing `token_burn` pure tests must pass UNCHANGED — if they need editing, the
  decision layer was not kept pure and the change is wrong.

## Approval log
