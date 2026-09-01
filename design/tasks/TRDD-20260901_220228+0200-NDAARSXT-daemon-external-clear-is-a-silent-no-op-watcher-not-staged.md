---
trdd-id: NDAARSXT
title: The keepalive daemon's external clear is a silent no-op — the watcher is not in the staged closure
column: complete
created: 2026-09-01T22:02:28+0200
updated: 2026-09-02T00:56:00+0200
current-owner: janitor-main-session
task-type: bugfix
scope: project
project-id: ai-maestro-janitor
severity: high
min-approval-requirement: none
blocked-by: []
npt: []
eht: []
relevant-rules: []
external-refs: [TRDD-PXP08ZQC, TRDD-1QJIZFFW, TRDD-2F3I2P18, TRDD-COQN6KVA, TRDD-ZM5LZ24Y]
implementation-commits: [f0bba94c]
---

# Every 5 minutes the daemon "runs" the external clear and does nothing, silently

## Measured 2026-09-01 (not inferred)

- The keepalive daemon (pid 43176, etime 3d) executes the **staged** tree in the plugin DATA
  dir — `daemon_keepalive_entry.py` does a static `import daemon` beside itself after
  `keepalive_boot.verify_or_restage` (deliberate, CPV C3: no runtime "latest version" exec).
- md5 of the staged files vs the cache: `scripts/daemon.py`, `lib/cold_cache_clear_task.py`,
  `lib/external_clear.py` all `== 3.4.1`; **`scripts/external_handoff_clear.py` is NOT
  STAGED** (absent from the closure). The restage stamp's file list confirms the closure:
  `daemon.py, lib/fleet_scan.py, lib/global_state.py, lib/harness_backend.py, lib/state.py,
  lib/terminal_trigger.py, lib/user_intent.py, oauth_rotator/rotator.py`.
- `cold_cache_clear_task.py:100-102` (staged copy): `watcher = _HERE.parent /
  "external_handoff_clear.py"; if not watcher.is_file(): return 0` — a SILENT return.
- `daemon.log`: 120 `cold-cache-clear` lines, every one "starting … done in 1s", no verdict,
  no decline, since the restage stamp epoch 1785947849 (2026-08-05).

So the daemon-driven external clear — the whole of TRDD-PXP08ZQC's abandoned-session lane —
has never run under the keepalive daemon. Enabling `CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_ENABLED`
changes nothing on this path. The 2026-08-15/16 "observed in production" cycles on PXP08ZQC
predate the keepalive staging (or ran through the SessionStart lane), which is why nobody saw
the lane die. The task's own comment, three lines below the silent return, warns about
"a permanent no-op that logs nothing and looks exactly like 'no session needed clearing'".

## Why the closure misses it (root cause, read 2026-09-01)

`keepalive_stage.daemon_closure()` is a **BFS over absolute imports** from the entry + daemon.
`external_handoff_clear.py` is reached only by **subprocess** (`cold_cache_clear_task` execs
it), never imported — so it is excluded by construction, and so is every module only it
imports. Any fix via option (a) must add an explicit "subprocess-reached extras" list to the
closure (or a deliberate import edge), not just append one file; option (b) sidesteps the
closure entirely.

## Fix (two halves, both required)

1. **Never silent.** Replace the bare `return 0` with a logged line AND an outcome stamp
   (`state.record_outcome("cold-cache-clear", "declined:watcher-not-staged")`, TRDD-COQN6KVA)
   so the next person sees it on disk in one `ls`.
2. **Make the watcher reachable from the staged daemon.** Either (a) add
   `external_handoff_clear.py` and its import closure (`active_skills`, `external_clear`,
   `handoff_files`, `cold_cache_compact`, `dispatch`, `fleet_scan`, `fleet_restart`,
   `clear_trigger`, `agentlens_probe`, …) to the staged closure computed by
   `scripts/lib/keepalive_stage.py::daemon_closure()` (consumed by `keepalive_boot.
   stage_mismatches` and `launchd_keepalive`'s restage) — big, and every new import
   silently re-breaks it; or (b) have `cold_cache_clear_task` resolve the watcher from the
   trusted cache scripts dir (`launchd_keepalive.latest_cache_scripts_dir()`, already used by
   `verify_or_restage`) when it is absent beside the staged tree — small, and the watcher then
   runs the newest INSTALLED code, which is what the drill wants. Prefer (b); record why.
3. A test that fails when the watcher is unreachable from a staged layout (simulate: a dir with
   only the closure files) — the exact shape that shipped dark.

## Acceptance

- [x] the missing-watcher path logs + stamps an outcome (never a bare return)
- [x] the staged daemon can invoke the watcher — option (b): falls back to
      `launchd_keepalive.latest_cache_scripts_dir()` (the same source the daemon restages from)
- [x] test pins the staged-layout case (cache-resolved path + declined stamp); 5/5 in
      `test_cold_cache_clear_server_lane.py`, ruff + mypy green — re-run by the approver
- [x] after the next publish + restage: a real VERDICT line from `cold-cache-clear` — measured
      2026-09-02: `cold-cache-clear.log` (the component's own sink, where the watcher's stdout
      lands) carries `VERDICT HOLD trigger=- why=context 222640 < 300000` at 00:42:08 and
      00:47:19, emitted by the daemon respawned at 23:43:56 after the 3.4.3 auto-update
      (`os-keepalive: newer version staged → exit for respawn`; staged
      `cold_cache_clear_task.py` md5 == cache 3.4.3). The lane silent since 2026-08-05 speaks.

## Notes and lessons learned

- Found while preparing the post-3.4.2 drill: checking WHICH tree the daemon executes
  (staged vs cache) before flipping a lever. The lesson generalizes: a version on disk is not
  the version running; measure the process's tree (md5 vs cache), not the cache dir listing.

## Approval log

- 2026-09-02T00:56:00+0200 — COMPLETE, closed by the implementing session under the USER's
  delegated review authority ("i've put you in charge", 2026-09-01). All four boxes hold; the
  last one is a log line the restaged daemon wrote on its own, not the session's word. Fix
  shipped in 3.4.3 (commit f0bba94c; tag verified first-hand, CI green). Self-closure disclosed:
  implementer and approver are the same session.
