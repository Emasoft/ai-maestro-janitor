---
name: janitor-keepalive-test-isolation-fsevents
description: "a unit test wrote to the REAL ~/.claude/janitor-global-state or the real plugin DATA dir / a test polluted production state / the janitor drove fseventsd to 39GB and crashed the machine / how to isolate janitor global-state + DATA in tests / a module-level Path.home() constant froze the dir at import so monkeypatch(HOME) never reached it / why the L0 keepalive restage churns the filesystem / JANITOR_GLOBAL_STATE_DIR + JANITOR_DATA_DIR isolation levers (NOT CLAUDE_PLUGIN_DATA) / how to root-cause an fseventsd or mds RAM/CPU runaway"
ocd: 2026-07-03
lmd: 2026-07-03
metadata:
  node_type: memory
  type: project
  tier: component
---

# L0 keepalive — call-time state resolution, test isolation, and bounded restage (the fseventsd-runaway class)

**Governed by:** [[janitor-architecture]] — the immortality L0–L3 keepalive/watchdog
layers and the scope invariant.

## The failure (TRDD-ZNN0UK5K, 2026-07-03)

A **39 GB / 97 %-CPU `fseventsd`** crashed the host. Root cause was inside the
janitor's own **L0 OS-keepalive**: `keepalive_boot._LOG_DIR` and
`launchd_keepalive._DATA_DIR` were module-level `Path.home()/…` constants
**evaluated at IMPORT time**. So a per-test `monkeypatch.setenv("HOME", tmp)` never
reached them, and the keepalive tests (`test_keepalive_boot/stage/launchd/entry`,
`test_daemon_maintenance_keepalive`) wrote their `_loud()` narration into the
**REAL** `~/.claude/janitor-global-state/daemon-keepalive.boot.log` AND — via
`verify_or_restage → _repair → restage` against ephemeral pytest tmp caches —
**restaged the real plugin DATA closure from tmp dirs that then vanished**,
leaving the real staged closure pointing at deleted paths. Every subsequent REAL
keepalive boot then found the closure "corrupt/incomplete" and re-copied the whole
~16-file closure verbatim (fresh `.tmp.<pid>` fsevents each), with **no backoff and
an unbounded boot log** — an fsevents firehose, tipped over the edge by a 99 %-full
disk that starved fseventsd's per-volume log flush. Proof: pytest tmp paths
literally appear in the production boot log.

## The lessons

1. **Every janitor global-state / DATA writer MUST resolve its dir AT CALL TIME**,
   honoring the isolation env — never a module-level `Path.home()`/frozen constant
   computed at import. Import-time capture is invisible to a test's
   `monkeypatch.setenv`, so the writer silently escapes isolation and hits real
   state.[^1] Fix shape: a `_state_dir()` / `data_dir()` function that re-reads the
   override each call (the sibling fixes were `keepalive_boot._state_dir()` +
   `launchd_keepalive.data_dir()`).
2. **The isolation levers are `JANITOR_GLOBAL_STATE_DIR` (global-state) and
   `JANITOR_DATA_DIR` (the DATA dir)** — the same override `version_update_lib._data_dir()`
   already uses. **NOT `${CLAUDE_PLUGIN_DATA}`**: that env resolves to whichever
   plugin owns the CURRENT turn (wrong in the detached daemon, and in any session
   where another plugin owns the turn — e.g. `fleet_status`'s keepalive probe). A
   keepalive/daemon test fixture must set `HOME` + `JANITOR_GLOBAL_STATE_DIR` +
   `JANITOR_DATA_DIR` (+ `CLAUDE_PLUGIN_DATA` as defense), env-based so a subprocess
   re-import inherits the same tmp tree.
3. **A self-heal / restage loop MUST be bounded.** Backoff on the mismatch
   *signature* (skip an identical still-mismatched restage within a cooldown —
   `CLAUDE_PLUGIN_OPTION_KEEPALIVE_RESTAGE_COOLDOWN_S`, default 300 s) so a
   non-converging closure stops re-copying, and size-rotate the log. An unbounded
   verbatim file-copy loop is the fsevents source; a persistent-mismatch that
   copies on every boot is the pathological case.
4. **`fseventsd` (and `mds`/Spotlight) is the SYMPTOM, not the leaker.** It balloons
   when FS-event production — a process creating many *unique* paths in a loop —
   outpaces its log flush, and a near-full disk makes flushing worse. Forensics:
   snapshot `ps` to a FILE then grep the file (never `pgrep`/`ps|grep` — they
   self-match); check `launchctl list` + `~/.claude/janitor-global-state` (daemon
   pid/heartbeat, kill-switch, `daemon-keepalive.boot.log`); confirm claude procs'
   `ppid` (ppid≠1 ⇒ user's own sessions, not daemon-resurrected); and rule out a
   SECOND churn source (`.maint-staging/` empty ⇒ the memory txn is clean; append
   logs like `token-meter.jsonl` coalesce and are not the driver).

## See also

- [[janitor-architecture]] — the L0–L3 immortality layers this component lives in.
- Same keepalive subsystem, related seam: the hub's TRDD-KEEPQRTN lesson (`[^3]`) —
  "a self-healing gate must be consulted by EVERY respawn path." Both are keepalive
  restage/respawn bugs that looked correct per-path but broke at the whole-surface
  seam.

## Notes and lessons learned

[^1]: [ocd:2026-07-03 lmd:2026-07-03] The keepalive tests had polluted the real
  boot log for weeks (pytest paths visible in the production
  `daemon-keepalive.boot.log`) before it cascaded into an OS crash — a
  test-isolation defect is not "just a test smell"; here it corrupted real staged
  state and took down the host. The tell: a *frozen* `Path.home()` module constant
  vs a test that only `monkeypatch.setenv("HOME", …)` — the env change lands AFTER
  the constant was already computed at import, so the two never meet. Verified fix +
  proof: janitor suite `pytest tests/` = 12028 passed AND `find
  ~/.claude/janitor-global-state -newermt "25 minutes ago"` empty during the test
  run (real state untouched).
