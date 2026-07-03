---
trdd-id: ZNN0UK5K
title: fseventsd runaway (39GB/97%) — L0 keepalive restage churn + test-state pollution
column: dev
created: 2026-07-03T06:04:36+0200
updated: 2026-07-03T06:04:36+0200
current-owner: janitor-session
assignee: janitor-session
priority: 0
severity: CRITICAL
effort: L
labels: [keepalive, fsevents, oom, test-isolation, immortality]
task-type: bugfix
parent-trdd: null
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
must-pass-tests-before-merge: true
test-requirements: [unit, lint]
review-requirements: []
implementation-commits: []
---

# TRDD-ZNN0UK5K — fseventsd runaway: L0 keepalive restage churn + test-state pollution

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-03

- **USER order (2026-07-03, verbatim):** "we got a problem. i had to kill a
  runaway fseventsd process that was at 39 Gb of ram usage and 97% of cpu usage.
  clearly the janitor or some other process is leaking and crashing the system.
  investigate and find a permanent solution." (A session `/goal` Stop-hook gates
  stopping until this is permanently solved.)

- **fseventsd = macOS FS-events daemon.** It balloons when the FS-event
  production rate outpaces its ability to flush per-volume logs (worsened by a
  99%-full disk) and/or a process churns a large number of unique paths. It is NOT
  a janitor process — but the janitor can DRIVE it via filesystem churn.

- **Forensic snapshot (saved: scratchpad/forensics-1.txt, forensics-2.txt):**
  - fseventsd now PID 34136, RSS 12 MB, etime ~42 min → **restarted after the
    user's kill; healthy now. No active runaway this instant.**
  - Global janitor **daemon DEAD ~30 h** (kill-switch.flag present since Jul-1
    23:53 "USER token-burn emergency"; last heartbeat 1782942874 vs now
    1783051001). NOT the active cause. Last daemon activity: `session-liveness`
    firing 38× `rearm` keystroke-injections into iTerm panes (fleet-recovery) →
    keystrokes, not fsevents.
  - **14 concurrent `claude --continue` procs, 0 with ppid==1** → the user's own
    fleet, NOT daemon-resurrected. (rung-7 resurrect did NOT fire.)
  - No launchd/systemd janitor job registered (`launchctl list` none; no
    LaunchAgents) → L0 keepalive DORMANT now.
  - Disk **99% full** (31 G free of 1.9 T) → fseventsd can't flush fast → RAM
    balloons. (User-side; the janitor's write VOLUME is what tips it over.)

- **✓ CONFIRMED ROOT-CAUSE CHAIN (verified by reading `daemon-keepalive.boot.log`
  (429 lines) + the source):**
  1. **Test-state pollution (the root).** `keepalive_boot.py:57`
     `_LOG_DIR = Path.home()/".claude"/"janitor-global-state"` is a **module-level
     constant frozen at import** — it ignores `JANITOR_GLOBAL_STATE_DIR`. And
     `launchd_keepalive.data_scripts_dir()` / `latest_cache_scripts_dir()` read
     real env. So the keepalive TESTS (test_keepalive_boot/stage/launchd/entry)
     write their `_loud()` narration into the **REAL** boot log (pytest tmp paths
     `pytest-of-emanuelesabetta/pytest-15xx/…/keepalive_install.sh` + `kaboom`
     appear IN the production log — proof) AND, via `verify_or_restage → _repair`
     (line 119 `is_data = staged==data_scripts_dir()` → True when
     `CLAUDE_PLUGIN_DATA` isn't overridden), RE-STAGE the **real**
     `$CLAUDE_PLUGIN_DATA` closure from an EPHEMERAL pytest tmp cache that then
     vanishes → the real staged closure now diverges from the real cache.
  2. **Restage churn.** Every subsequent REAL keepalive boot then finds the
     closure "corrupt/incomplete" and RE-STAGES it — verbatim `shutil.copyfile`
     of ~16 files (`keepalive_stage.stage_closure`, unique `.tmp.<pid>` names →
     fresh fsevents each). `verify_or_restage` has **no backoff/dedupe**, so a
     persistent mismatch (or a cache-version flip) copies files on EVERY boot.
     The log shows the non-converging state: "restage left N file(s) still
     mismatched — proceeding".
  3. **Unbounded boot log.** `_loud` uses `.open("a")` with **no rotation** →
     429 lines and growing.
  4. **Respawn-storm recurrence risk.** launchd `KeepAlive` + a crash-on-start
     daemon → respawn → verify_or_restage → copy → respawn … a tight
     file-copy/process storm. Dormant now (kill-switch), but re-arms when the
     switch clears unless throttled + bounded.

- **Confidence:** the four janitor defects above are VERIFIED (log + code). The
  exact process that drove fseventsd to 39 GB is NOT reproducible (the event is
  gone), but these are the janitor's plausible, unbounded FS-churn contributions;
  the permanent solution eliminates every one + adds detection for the class.

- **PERMANENT SOLUTION (fix ALL; A+B are the core, C hardens recurrence, D detects
  the class, E cleans up):**
  - **FIX A — test isolation (root).** (A1) `keepalive_boot._loud` writes to
    `global_state.global_state_dir()` (honors `JANITOR_GLOBAL_STATE_DIR`),
    resolved at CALL time — never a frozen `Path.home()`. (A2) Every keepalive
    test (`test_keepalive_boot`, `test_keepalive_stage`, `test_launchd_keepalive`,
    `test_daemon_keepalive_entry`, `test_daemon_maintenance_keepalive`) uses an
    autouse fixture setting tmp `HOME` + `CLAUDE_PLUGIN_DATA` +
    `JANITOR_GLOBAL_STATE_DIR`; add a regression test asserting a
    `verify_or_restage`/`_loud` call NEVER writes under the real global-state dir.
  - **FIX B — bound the churn.** (B1) restage backoff/dedupe: stamp last-restage
    ts + mismatch-signature (sorted rel-paths) in the global-state dir; skip the
    copy + log once (rate-limited) when the SAME mismatch recurs within a cooldown
    (default 300 s, env-tunable). (B2) rotate the boot log (cap ~256 KB → `.1`),
    reusing the `state.rotate_log_if_big` pattern.
  - **FIX C — restart throttle.** Ensure the launchd plist sets `ThrottleInterval`
    (≥30 s) and the systemd unit `RestartSec`/`StartLimitIntervalSec` so a
    crash-looping daemon can't hammer respawn→restage. Audit `launchd_keepalive`
    installer; add if missing.
  - **FIX D — failure-class detection (opt-safe, alert-only).** `memory-guard`
    only kills janitor-OWNED runaways ("only janitor-owned runaways are
    killable"), so a system daemon (fseventsd/mds) driven runaway is invisible.
    Add a heartbeat detector that flags fseventsd/mds RSS over a threshold (e.g.
    4 GB) AND/OR disk >95% full → one drift line, so the agent/user is warned at 4
    GB, not 39 GB. (May land as a child TRDD.)
  - **FIX E — one-shot cleanup.** Rotate/truncate the polluted real boot log
    (429 lines of pytest garbage) — safe, regeneratable.

- **Load-bearing facts / gotchas:**
  - Standing constraint: **do NOT clear the global kill-switch or re-arm the
    fleet.** The kill-switch keeping the daemon dead is the SAFE state; leave it.
  - Do NOT touch the user's 14 running claude sessions.
  - lean-ctx shell allowlist blocks `{` brace-groups, shell `func()` defs, and
    `python3 -c` — put logic in a script file and run `bash file` / `uv run file`.
  - Isolate janitor global state in tests via `JANITOR_GLOBAL_STATE_DIR` +
    `HOME` + `CLAUDE_PLUGIN_DATA` (per CLAUDE.md test conventions).
  - Ship via `publish.py` (CPV `--strict` gate — no NIT/MINOR/MAJOR/CRITICAL).

- **NEXT ACTION:** implement FIX A + FIX B in `keepalive_boot.py` + isolate the 5
  keepalive test files (delegate one agent per file cluster, serial, opus, TDD);
  run the keepalive tests; then FIX C (throttle audit), FIX E (cleanup), FIX D
  (detector). Verify ruff/pyright + `pytest tests/test_keepalive*.py
  tests/test_daemon_keepalive_entry.py tests/test_daemon_maintenance_keepalive.py`.
  Commit WHY-rich per fix. This does NOT block on the earlier v0.30.0 publish /
  TRDD-2KQQAEPP — but ships in the same next release.

## Durable artifacts to read before acting
- scratchpad/forensics-1.txt, scratchpad/forensics-2.txt — the raw snapshots.
- `scripts/lib/keepalive_boot.py` (197 L), `keepalive_stage.py` (98 L),
  `launchd_keepalive.py` (245 L), `scripts/daemon_keepalive_entry.py` (64 L).
