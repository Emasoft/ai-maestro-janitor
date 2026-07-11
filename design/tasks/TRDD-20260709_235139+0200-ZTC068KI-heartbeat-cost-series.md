---
trdd-id: ZTC068KI
title: Opt-in per-fire cost series — record the previous fire's exact cost to a log
column: complete
created: 2026-07-09T23:51:39+0200
updated: 2026-07-11T13:25:00+0200
current-owner: janitor
assignee: janitor
priority: 3
severity: LOW
effort: S
labels: [heartbeat, token-economy, observability]
task-type: feature
approval-tier: 0
parent-trdd: null
npt: []
eht: []
blocked-by: []
supersedes: []
superseded-by: []
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
must-pass-tests-before-merge: true
test-requirements: [unit, lint]
audit-requirements: []
review-requirements: []
runtime-targets: [macos, linux]
impacts: [config-schema]
attempts: 0
test-failures: 0
last-test-result: pass
last-test-at: 2026-07-09T23:50:00+0200
implementation-commits: []
external-refs: ["github.com/Emasoft/ai-maestro-janitor/issues/78"]
---

# Opt-in per-fire cost series — record the previous fire's exact cost to a log

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-09

**IMPLEMENTED locally, NOT yet published.** janitor#78's proposal, adopted with one
deliberate deviation (log file, not stdout — see D1).

- `dispatch._phase_heartbeat_cost()` — runs the command in
  `CLAUDE_PLUGIN_OPTION_HEARTBEAT_COST_COMMAND` (default `""` = OFF) on every fire,
  full AND maintenance mode, and appends its first stdout line to
  `.janitor/logs/heartbeat-cost.log`. Fail-open; 20 s timeout; failures diagnose to
  `dispatch.log`, never the series file.
- `plugin.json` declares `heartbeat_cost_command` (100th userConfig entry).
- `tests/test_heartbeat_cost_phase.py` — 8 tests, real subprocesses, incl. a
  source-order guard that the call site precedes the maintenance early-return.
- **Live-verified** on this machine with the real AgentLens CLI + server: stdout
  empty, series line landed —
  `The last heartbeat [2026-07-09T21:46:35Z] cost 7,735,084 tokens = $6.0853 … (15 API calls)`.

**NEXT ACTION:** ships with the next release (rides whatever bumps next). Comment on
janitor#78 is posted. To ENABLE on this machine, set in the plugin's userConfig:
`heartbeat_cost_command: "node ~/Code/agentlens/scripts/agentlens-heartbeat-cost.js --oneline"`.

## Problem

janitor#78 (from the agentlens Claude): each fire re-reads the session's full cached
prefix, so heartbeats on a large session cost real money that nobody sees — measured
$0.70–$1.57 per fire on a ~440k prefix, and $6.09 on one fire of THIS session at
~570k after cache-miss rewrites. The AgentLens CLI computes the EXACT cost of the
last settled fire from the OTEL corpus. The proposal: run it as the last step of each
fire and emit one greppable line.

## Design decisions

**D1 — the line goes to a LOG, not to the fire's stdout.** This is the one deviation
from the issue's letter, and it is load-bearing. The heartbeat's zero-output contract
(the token-economy fix that makes quiet fires cheap) means every byte a fire prints is
surfaced by the model, spending output tokens on EVERY fire — a per-fire stdout cost
line would tax the exact thing it exists to measure, forever, on all-quiet fires. The
issue's own flag help says the line is "for the heartbeat log", and the user studies
the SERIES; `.janitor/logs/heartbeat-cost.log` (structurally rotated, S3/S4-bounded)
IS the series, greppable at zero marginal token cost.

**D2 — the command is config, not code.** The CLI lives in a machine-local checkout
(`~/Code/agentlens`, unpublished) and needs a local server. Hard-coding either would
break every other machine; the issue itself asks for config. Default-off keeps the
fleet inert until the user opts a machine in.

**D3 — it runs in maintenance mode too.** Maintenance fires exist to be cheap; their
measured cost is precisely what decides whether the cadence is worth keeping. The call
site sits before the maintenance early-return, and a source-order test pins that.

**D4 — failures diagnose to `dispatch.log`, never the series.** `run_subprocess`
logs its failure line to `<detector_name>.log`; pointing that at the series file
would salt the data with error lines every fire the server is down. Non-zero exit is
the CLI's documented "no cost line this fire" — silent by contract.

**D5 — position within the fire is immaterial; mode coverage is not.** The CLI can
only report the last SETTLED fire (an OTEL body has no request_id; a call's tokens
become knowable only when the next call is written), so "last step" buys nothing —
but running in only one mode would blind the series to the other. Skipped fires
(pause / rate-limit / compact early-returns) leave holes in the series, never wrong
values: each invocation reports whatever fire settled last.

## Notes and lessons learned

The first test run failed on the missing-binary case because `run_subprocess` was
passed `detector_name="heartbeat-cost"` — its failure diagnostic CREATED the series
file the test asserted absent. The helper's logging target and the phase's data file
collided in a way neither piece documents loudly. D4 is the fix; the renamed test
(`…never_salts_the_series`) pins both halves.
