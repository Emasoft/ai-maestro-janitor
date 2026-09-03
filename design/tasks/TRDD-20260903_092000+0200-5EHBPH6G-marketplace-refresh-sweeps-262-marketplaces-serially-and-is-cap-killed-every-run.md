---
trdd-id: 5EHBPH6G
title: marketplace-refresh sweeps 262 registered marketplaces serially under background QoS and is cap-killed on every run — five consecutive rc=-9 and plugin updates deferred behind its lock
column: todo
created: 2026-09-03T09:20:00+0200
updated: 2026-09-03T09:20:00+0200
current-owner: janitor-main-session
task-type: bugfix
priority: high
severity: high
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
labels: [daemon, marketplace, plugin-update, workload-cap]
relevant-rules: []
blocked-by: []
npt: []
eht: []
implementation-commits: []
created-by: heartbeat drift line 2026-09-03 03:06 + diagnosis report
---

# marketplace-refresh is cap-killed on every run

## Measured (daemon.log, 2026-09-03)

| run start | outcome |
|---|---|
| 00:54 | FAILED in 1938 s, rc=-9, consecutive=2 |
| 02:27 | child pid 73836 exceeded the workload cap — killed; FAILED 1937 s, consecutive=3, quarantined +3600 s |
| 04:59 | child pid 77569 killed 05:31; FAILED 1934 s, consecutive=4 |
| ~06:30 | consecutive=5 |

While the child runs it holds `global-state/marketplace-op.lock`, so every
`plugin-update` fire logs `deferred (marketplace lock held)` — the fleet stops updating for
the whole 32-minute window, every hour. The completion stamp
`marketplace-refresh.last-run.ts` is written on failure too, so nothing reported this until the
heartbeat's task-quarantine drift line.

## Cause (diagnosis: `reports/board-drain/20260903_091701+0200-marketplace-refresh-diagnosis.md`)

- The task runs `claude plugin marketplace update` for **all registered marketplaces
  serially**. This host has **262** entries in `~/.claude/plugins/known_marketplaces.json`
  (289 dirs under `~/.claude/plugins/marketplaces/`) — the corpus-distillation work registered
  hundreds of one-off community marketplaces that back no installed plugin.
- The child runs under `taskpolicy -b` + nice (`daemon.py:512`, `daemon_throttle.py`), so
  262 serial network fetches at background QoS exceed the 1800 s inner deadline
  (`daemon.py:323`, `437-456`) — which never actually fires — and are SIGKILLed only by the
  outer 1920 s watchdog (`daemon.py:2488-2498`). Hence the constant ~1935 s / rc=-9.

## Fix

1. **Refresh only marketplaces that back an installed plugin** (derive the set from
   `installed_plugins.json` / the cache dir), plus the ones named in
   `CLAUDE_PLUGIN_OPTION_MARKETPLACE_REFRESH_EXTRA`. On this host that is a handful, not 262.
2. Per-marketplace timeout (`CLAUDE_PLUGIN_OPTION_MARKETPLACE_REFRESH_PER_ITEM_S`, default
   60) so one hung remote cannot consume the whole budget; a timed-out entry is logged and
   skipped, never retried in the same run.
3. Make the inner 1800 s deadline actually fire (it is dead code today) and write
   `last-run.ts` **only on success**; on failure write `last-failure.ts` so the stale-stamp
   detector sees the truth.
4. Surface the count: the task logs `refreshed N/M marketplaces in T s`.

## Acceptance

- [ ] Unit test: with 3 installed plugins from 2 marketplaces and 200 registered ones, the
      refresh plan contains exactly those 2 (+ extras from the option).
- [ ] Unit test: a per-item timeout skips the entry and the run still succeeds.
- [ ] Unit test: the stamp is untouched after a failed run; `last-failure.ts` is written.
- [ ] Live: `daemon.log` shows one `marketplace-refresh` run finishing with rc=0 in < 300 s
      and `plugin-update` no longer logging `deferred (marketplace lock held)`.

## Approval log

## Notes and lessons learned
