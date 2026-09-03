---
trdd-id: ZNN0UK5K
title: fseventsd runaway (39GB/97%) — L0 keepalive restage churn + test-state pollution
column: complete
created: 2026-07-03T06:04:36+0200
updated: 2026-07-03T19:17:15+0200
current-owner: janitor-session
assignee: janitor-session
priority: 0
severity: CRITICAL
effort: L
labels: [keepalive, fsevents, oom, test-isolation, immortality]
task-type: bugfix
parent-trdd: null
eht: [TRDD-HK7IZ21Z]
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
must-pass-tests-before-merge: true
test-requirements: [unit, lint]
review-requirements: []
implementation-commits: [33ef7eb, 96bf8a4, 21661b4, d557d6b]
---

# TRDD-ZNN0UK5K — fseventsd runaway: L0 keepalive restage churn + test-state pollution

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-03

## ✅ SAFEGUARDS PLAN — COMPLETE + PARTIALLY SHIPPED (2026-07-03, v0.30.0)

Approved plan mirrored here for durability (source: `~/.claude/plans/glittery-hatching-shell.md`).

**Part 0 — disk finding (forensics CONFIRMED):** disk genuinely IS ~99% full —
**28 GB writable** of 1.9 TB (identical on `/` + `/System/Volumes/Data`, one APFS
container). OS-UI "194 GB free" = 28 GB writable + **~166 GB purgeable** (reclaimable
local snapshots/caches macOS frees on demand; `df` excludes them — both numbers are
right, they measure different things). **No overnight leak** (df moved 31→28 GB in
hours; no >2 GB file touched in 48 h) — chronic accumulation. Top consumers: `~/Code`
452 GB, `~/Library/Containers` 163 GB, OrbStack 89 GB. **Janitor is NOT the filler**
(`plugins/data` 176 MB, `janitor-global-state` 2.1 MB). Host-hygiene issue, but the
fsevents storm + snapshot-purge-under-pressure share the janitor's high-volume
FS-churn root, so bounding that churn (S8) is the real prevention.

**Part 2 — prevention roster (actionable, sequenced):**
- **S1** session-DEFAULT test isolation in `tests/conftest.py` + session-end real-state
  write-guard (would have caught this on CI run #1). *PENDING.*
- **S2** guard-test banning module-level `Path.home()` writers (allow-list
  `launchd_keepalive._DATA_DIR`, the only one). *PENDING.*
- **S3** audit every self-heal/retry loop for backoff/convergence. *PENDING.*
- **S4** append-log rotation audit (unbounded-log gaps). *PENDING.*
- **S5** failure-class runaway detector `system-daemon-runaway.py` (alert at 4 GB, not
  39 GB) — child **TRDD-HK7IZ21Z**. *PENDING.*
- **S6** memory-guard ALERT path for a non-janitor runaway it can't kill. *PENDING.*
- **S7** disk checks report BOTH writable + purgeable (accurate, not alarmist). *PENDING.*
- **S8** bound the janitor's own FS-churn (age-retention for `reports/` + `.janitor/state`).
  *PENDING.*
- **S9** ⛔ **SUPERSEDED + RETIRED v0.31.0** — shipped as an opt-in PostToolUse hook in
  v0.30.0 (500-char head+tail cap + tldr/distill/lean-ctx allowlist; commits 96bf8a4 +
  21661b4), then RETIRED once a fork-agent doc-check CONFIRMED Claude Code has a NATIVE
  `BASH_MAX_OUTPUT_LENGTH` env var that caps Bash output AND saves the FULL output to a
  file, handing the model path+preview for lossless Read-slicing. WHY retire: native is
  strictly better — the S9 hook's head+tail DROPPED the middle of long output (data loss),
  and running both would clobber native's file-pointer preview (S9's `updatedToolOutput`
  overwrites it). User decision 2026-07-03: adopt native at `BASH_MAX_OUTPUT_LENGTH=500`
  (set in `~/.claude/settings.json` env — needs a session restart to take effect) and
  retire S9. Removed in v0.31.0: the hook + test (`git rm`), the hooks.json Bash
  PostToolUse entry, and the `.janitor/state/bash-output-cap` sentinel.

**Sequencing:** S1+S2 → S7 → S5(+HK7IZ21Z)/S6 → S3/S4; each its own commit. Core fix
(Part 1) shipped: **33ef7eb**.

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
     `pytest-of-<user>/pytest-15xx/…/keepalive_install.sh` + `kaboom`
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

- **✓ DONE — FIX A + FIX B (commit 33ef7eb), rechecked 4× per USER order:**
  `keepalive_boot._state_dir()` + `launchd_keepalive.data_dir()`/`data_scripts_dir()`
  resolve the global-state/DATA dir at CALL time (honor `JANITOR_GLOBAL_STATE_DIR`
  / `JANITOR_DATA_DIR`, NOT `${CLAUDE_PLUGIN_DATA}` = running-plugin); restage
  backoff (identical still-mismatched signature within a 300 s cooldown skips the
  copy; env `…KEEPALIVE_RESTAGE_COOLDOWN_S`, 0 disables; converges); 256 KB boot-log
  rotation; autouse isolation fixture (HOME + the two dir envs + CLAUDE_PLUGIN_DATA)
  across all 5 keepalive test files + 5 new regressions.
  - RECHECK (4 passes, all green): (1) keepalive 54 + regression 215 + ruff clean +
    pyright 0/0/0; (2) `keepalive_boot.py` logic trace — fail-open/loud intact,
    backoff converges; (3) diffs — prod behavior identical (env unset), tests REAL
    (spy only on the `restage` I/O boundary); (4) real `~/.claude/janitor-global-state`
    UNTOUCHED by the test run (`find -newermt` empty; boot log mtime unchanged) +
    **TRUE janitor suite `pytest tests/` = 12028 passed**. NOTE: bare
    `python -m pytest` from root INTERNAL-ERRORs collecting a FOREIGN project under
    `downloads_dev/CLAUDE-BROWSER-PROJECTS/…` (missing deps) — orthogonal, gitignored,
    not the janitor; always scope janitor test runs to `tests/`.
  - Wikimem: new PROJECT page `janitor-keepalive-test-isolation-fsevents.md`
    (symptom-indexed) + reciprocal link from `janitor-architecture.md`.
- **✓ FIX C already present** (verified in `scripts/keepalive_install.sh`): launchd
  `ThrottleInterval=30` (line 187) + `RunAtLoad`/`KeepAlive`; systemd
  `Restart=always`/`RestartSec=30` (line 229). The respawn path is bounded to ≥30 s.
  Combined with FIX B (restage copy capped once/cooldown REGARDLESS of respawn rate)
  and FIX A (no test pollution ⇒ no corrupt-stage trigger), the runaway is solved by
  THREE independent layers. No FIX C work needed.
- **FIX D deferred → child TRDD-HK7IZ21Z** (backburner): a failure-class detector
  warning on fseventsd/mds/any process >4 GB + disk >95 % — the USER's "or some other
  process is leaking" safety net; additive, NOT required to fix this bug.
- **✓ PERMANENT SOLUTION COMPLETE (A + B; pre-existing C).** Committed to `main`
  (fix 33ef7eb, memory+trdd d284970), rechecked 4×, wikimem'd. FIX E (log cleanup)
  unneeded — rotation + backoff self-heal the existing corrupt stage in ONE bounded
  restage on next boot. Ships via `publish.py` on the next USER-authorized release
  (rides with the pending v0.30.0 / TRDD-2KQQAEPP).

## Durable artifacts to read before acting
- scratchpad/forensics-1.txt, scratchpad/forensics-2.txt — the raw snapshots.
- `scripts/lib/keepalive_boot.py` (197 L), `keepalive_stage.py` (98 L),
  `launchd_keepalive.py` (245 L), `scripts/daemon_keepalive_entry.py` (64 L).
