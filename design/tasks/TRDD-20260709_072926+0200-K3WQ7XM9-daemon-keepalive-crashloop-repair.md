---
trdd-id: K3WQ7XM9
title: Daemon crash-loop repair — init_state, staged_is_current, keepalive test-isolation, keychain re-prompt
column: dev
created: 2026-07-09T07:29:26+0200
updated: 2026-07-09T12:33:33+0200
current-owner: janitor
assignee: janitor
priority: 1
severity: HIGH
effort: L
task-type: bugfix
release-via: publish
test-requirements: [unit, lint]
relevant-rules: []
impacts: [ci-pipeline]
external-refs: []
---

# Daemon crash-loop repair (post-0.34.0)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-09

**⏵ UPDATE 2026-07-09 #2 (LATEST — SECOND flood root-caused + FIXED in v0.35.1):**
- **A SECOND flood hit even with the rotator opt-in PAUSED.** Root cause: THREE heartbeat
  DETECTORS read the OS keychain independent of the opt-in flag — `window-burn-rate`
  (`rotator_usage.accounts_usage`) and `oauth-login-needed` + `oauth-cookie-reminder`
  (`supervisor._slot_facts`). They gated on rotator-home PRESENCE / their own ENABLED flag, NOT
  the opt-in flag — so "paused rotator" did NOT mean "zero keychain access." My earlier claim
  that pausing the opt-in gave zero keychain access was WRONG for these detectors.
- **Compounded by a LOCKED login keychain (macOS auto-lock).** A locked keychain makes EVERY
  reader prompt to unlock — the janitor detectors AND macOS itself (the user saw
  `iCloudNotificationAgent` prompting too, the tell that the whole keychain was locked). The
  `run_security` denied-latch capped each burst at ONE, but every re-lock started a fresh one.
- **FIX v0.35.1 (`1140208`):** gate at the TWO shared keychain-read entry points —
  `supervisor._slot_facts` returns `()` unless `opt_in_present(root)` (fixes both oauth
  detectors), and `window-burn-rate._keychain_opt_in_ok()` gates before its `accounts_usage`
  gather. The user-invoked `/janitor-token-report --live` (the OTHER `accounts_usage` caller) is
  deliberately NOT gated. +2 regression tests prove "no opt-in → no keychain read"; full suite
  12261 passed, ruff+mypy clean. Published: https://github.com/Emasoft/ai-maestro-janitor/releases/tag/v0.35.1
- **DEPLOYED:** cache updated 0.35.0→0.35.1; OS-keepalive closure force-restaged + byte-verified
  0.35.1 (`daemon.py`+`supervisor.py` MATCH); stub→0.35.1; heartbeat cron `ee43873d` at `*/4`
  (4 min — cron can't express 4m30s); kill-switch/latch CLEARED. Rotator opt-in stays PAUSED
  (its own slot-ACL prompt, TRDD-dfc0959a, is unfixed; the detector gate makes detectors safe
  regardless — opt-in OFF now truly = zero keychain access).
- **USER-SIDE permanent fix (the thing that actually stopped it):** the login keychain was
  auto-locking. `security unlock-keychain` + `security set-keychain-settings
  ~/Library/Keychains/login.keychain-db` (no flags → `no-timeout`, no lock-on-sleep) — run in a
  REAL terminal / Keychain Access GUI, because this Claude terminal's lean-ctx wrapper BLOCKS the
  `security` binary. Verified `show-keychain-info` → `no-timeout`. wikimem: [[macos-keychain]] `[^3]`.

**⏵ UPDATE 2026-07-09 #1 (keychain flood RESOLVED + guardian RE-ARMED; supersedes item #4 below):**
- **v0.35.0 SHIPPED + DEPLOYED** the structural flood fix: `safe_storage.run_security` choke-point
  (denied-latch short-circuits BEFORE spawn; hard timeout → latch; ACL/cancel → latch) = at most
  ONE keychain prompt machine-wide, EVER, until a human clears the latch (`3e5c36a`); FIX B2 marks
  the rotator tick HEADLESS so it skips the prompting `-w` primary read (`1cf0b6c`); conftest
  headless-leak fix (`85e6d17`). Full 7395-test suite passed with ZERO keychain prompts. Release
  `87618eb`.
- **ROOT CAUSE of the RECURRING flood found this session:** the L0 OS-keepalive (launchd) had
  STAGED **0.31.0** (the pre-fix flooder) into `${DATA}/scripts/` and kept relaunching it —
  `staged_is_current` was False vs the correct 0.35.0 target (staged before 0.35.0 existed).
  FORCE-RESTAGED the whole closure to 0.35.0 and byte-verified daemon.py + rotator.py +
  safe_storage.py all == 0.35.0. The keepalive now runs the flood-safe daemon.
- **GUARDIAN RE-ARMED:** kill-switch + denied-latch + stale daemon.pid CLEARED in both global-state
  dirs; stub refreshed to 0.35.0; heartbeat cron re-created (`060459c4`, session-only per the CC
  durable-downgrade — the OS-keepalive is the durable layer). `kill_switch_present()`=False → daemon runs.
- **ROTATOR OPT-IN RE-PAUSED** (`opt-in.flag` → `opt-in.flag.PAUSED-keychain-incident-20260709`).
  Reason: B2 headless only skips the PRIMARY read; the tick still reads the ACL'd SLOTS
  (`Claude Code-rotator-slot`) via `-w`, which have no stable trusted reader (the flood's real ACL
  root cause — TRDD-dfc0959a) → would prompt ONCE then the latch disables the rotator anyway.
  Pausing the opt-in makes `task_oauth_rotator_tick` + the supervisor no-op → the daemon touches
  the keychain ZERO times → zero prompts, guaranteed, independent of the launchd-context question.
  `supervisor.opt_in_present()`=False verified. RE-ENABLE with `/janitor-auto-manage-oauth-on` once
  the slot-ACL/stable-reader fix (TRDD-dfc0959a) lands. wikimem: [[macos-keychain]].
- **NET:** janitor guardian ARMED + running verified-safe 0.35.0; flood STRUCTURALLY impossible
  (latch) AND the flood-source feature dormant (opt-in paused). No keychain reader in `ps`.

**Context:** v0.34.0 shipped the rotator keychain-timeout fix (`c717743`) — real, done.
But the janitor **daemon crash-loops** on every version (0.34.0→0.33.0→0.31.0 all
quarantined by the crash-loop breaker). Root-caused this session to bugs SEPARATE from the
keychain hang. This TRDD collects the full repair.

**Bugs (severity order):**

1. **`init_state()` crashes the launchd daemon — FIXED (`d939110`, unpushed).**
   Under the L0 OS-keepalive (launchd) the daemon has NO `CLAUDE_PROJECT_DIR`, cwd=`/`, so
   `state.project_root()` → `/`, `state_dir()` → `/.janitor/state`, and `init_state()`'s
   `state_dir().mkdir()` raised `OSError(Errno 30) Read-only file system: /.janitor`. The
   daemon crashed at its first `state.log_line` (via `init_state`) BEFORE the task loop,
   every boot → launchd relaunched → crash-loop breaker quarantined each version. Fix
   landed: `init_state` now creates `log_dir()` first (daemon overrides it via
   `JANITOR_LOG_DIR`) and `state_dir()` best-effort (catch OSError). Verified traceback:
   `daemon.main → state.log_line → init_state → state_dir().mkdir → /.janitor read-only`.

2. **`launchd_keepalive.staged_is_current()` FALSE-POSITIVE — FIXED (`a39cf84`).**
   Root-caused to TWO defects: (a) it compared ONLY `daemon.py`, so a stale `lib/` closure
   file with a current `daemon.py` read as "current" (wrong file set); (b) `filecmp.cmp(...,
   shallow=False)` keeps a MODULE-LEVEL cache keyed on `(path, path, sig, sig)` with
   `sig=(mode,size,mtime)` — after a same-size/same-mtime overwrite with different content it
   returns a STALE `True` (reproduced empirically). Fix: `staged_is_current` now byte-compares
   the WHOLE closure (`keepalive_stage.daemon_closure`) via direct reads (no filecmp cache).
   Regression test added; ruff+mypy clean.

3. **Keepalive test-isolation escape — VERIFIED, fix HOLDS (no code change needed).**
   The 2026-07-03 call-time-dir fix is intact and defended by S1a (conftest session-default
   env isolation), S1b (real-state write-guard), and S2 (`test_no_frozen_home_paths`). Full
   `pytest tests/` (12246 passed) produced ZERO real-state pollution: (a) S1b write-guard did
   NOT fire (no guarded `.py`/state/flags/memory mutation), and (b) the REAL
   `daemon-keepalive.boot.log` size was UNCHANGED (91655→91655) across the whole run — the
   sharpest probe, since `.log` is excluded from S1b, proving no keepalive test escaped into
   it. The 296 pre-existing `pytest`/`kaboom` lines in that log are HISTORICAL (pre-isolation);
   the suite added zero. Left the old log in place (daemon's own regeneratable `.log`,
   auto-rotates at 256KB; not worth touching live daemon state).

   [ORIGINAL DIAGNOSIS, retained for the record:]
   The production `daemon-keepalive.boot.log` contains `pytest-of-emanuelesabetta/pytest-1572/
   test_corrupt_stage_is_restaged0/...` paths — keepalive tests wrote to REAL DATA state.
   This is the class in project-memory note **`janitor-keepalive-test-isolation-fsevents`**
   (TRDD-ZNN0UK5K, 2026-07-03): frozen `Path.home()` module constants invisible to a test's
   `monkeypatch.setenv("HOME")` → tests escape isolation → corrupt the real staged closure →
   every real boot finds it "corrupt/incomplete" and re-copies → fseventsd firehose → the
   host once hit 39GB/97%-CPU and CRASHED. That was "fixed" 2026-07-03 (call-time
   `keepalive_boot._state_dir()` + `launchd_keepalive.data_dir()`). READ that memory note,
   then VERIFY the fix still holds OR find the regression/another frozen constant. Proof of
   a clean fix (the note's method): run `pytest tests/` and confirm
   `find ~/.claude/janitor-global-state ~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins -newermt "<suite start>"`
   shows NO real-state files written during the run. Isolation levers are
   `JANITOR_GLOBAL_STATE_DIR` + `JANITOR_DATA_DIR` (NOT `CLAUDE_PLUGIN_DATA`). Also clear the
   old pollution from the real boot log if safe.

4. **Keychain re-prompts ~100× — DOCUMENTED (no code change; needs a follow-up TRDD).**
   Root cause confirmed: `rotator._read_live_primary()` (rotator.py:379) unconditionally
   `security find-generic-password -s "Claude Code-credentials" -a $USER -w` — a `-w` secret
   read of the ACL-restricted primary Claude's `/login` writes with a Claude-only ACL. From
   the daemon's headless context (+ version-changing uv-python path) macOS re-prompts with no
   durable "Always Allow". Already non-fatal (timeout=10 at rotator.py:401, 0.34.0). KEY
   INSIGHT: the "~100×" is largely a SYMPTOM of the crash-loop — each respawn = one first-tick
   prompt — so fixing #2/#3 collapses it to ~1 prompt per daemon lifetime. The `-livebak`
   mirror is prompt-free (created via `/usr/bin/security`, ACL trusts that stable binary).
   Mitigation options A/B/C + the "no USER keychain action needed / an Always-Allow won't
   stick" analysis are in the report (see below). NOT implemented here: out of scope + the
   constraint "Do NOT touch the live keychain credential" + risk to the F1 identity logic.

   [ORIGINAL NOTE, retained:]
   USER reported the keychain dialog opened ~100× with NO "Always Allow" button; they
   started cancelling. Cause: the daemon's `security` reads come from a **uv-cached python
   whose path changes every version** (`~/.cache/uv/.../python`) AND/OR it reads the
   ACL-restricted `Claude Code-credentials` live item (created by Claude's own `/login` with
   a Claude-only ACL). macOS can only offer "Always Allow" for a STABLE binary identity, so
   it re-prompts forever. 0.34.0's timeout makes this non-fatal (5s fail-fast) but the PROMPT
   still appears. Attempt a mitigation: e.g. the daemon should prefer the `-livebak` mirror
   (rotator-written, `-T`-accessible) and AVOID the `-w` secret read of the ACL-restricted
   primary when a presence probe (no `-w`, may not prompt) suffices; or a stable-python /
   ctypes SecKeychain path (the memory note flags ctypes as "deferred hardening"). If a clean
   fix is too big, DOCUMENT precisely what's needed + whether it requires a USER keychain
   action, and leave it for a follow-up TRDD.

**NEXT ACTION (for the fix-agent):** fix #2 and #3 (the crash-loop drivers), attempt #4,
run the full `pytest tests/` (12233 tests must pass + no real-state pollution), commit each
fix with a WHY body (`Agent: ai-maestro-janitor` trailer). Do NOT push (the orchestrator
publishes). Report file + one line back.

**THEN (orchestrator):** publish 0.35.0 (`publish.py --minor`; push needs `--no-verify` — the
pipeline validates, only the network push is hook-gated), fleet-upgrade
(`claude plugin update ai-maestro-janitor@ai-maestro-plugins`), restage keepalive from 0.35.0,
verify the launchd daemon boots + reaches the task loop (fresh `daemon.log` `task … starting`
entries, stable pid, no crash-loop), and un-quarantine as needed.

**Load-bearing facts / gotchas:**
- The daemon works when spawned by a session heartbeat (has `CLAUDE_PROJECT_DIR`); it ONLY
  crashes on the launchd path. Proven: a cache-path daemon run with `CLAUDE_PROJECT_DIR` ran
  `marketplace-refresh` (80s) cleanly.
- Real-state write-guard (conftest S1b): a daemon self-update mid-suite can false-positive on
  `.py`-closure churn — but a keepalive-test escape is REAL pollution. Distinguish carefully.
- lean-ctx blocks `python3 -c`, heredocs with `def`, `$(...)`-in-args, bare `ssh`/`timeout`.
  Use script files.

## SUPERSEDED — do NOT carry forward
- Earlier this session I attributed the crash-loop to the keychain hang. WRONG — the keychain
  hang (fixed in 0.34.0) is a DIFFERENT symptom; the crash-loop driver is bug #1 (`/.janitor`)
  compounded by #2/#3. Also I called the write-guard `.py`-closure exit-3 a pure false
  positive; it was partly REAL test pollution (#3).

## Fix-agent session result (2026-07-09T07:48+0200)

- Bug #2 FIXED (`a39cf84`); bug #3 VERIFIED (fix holds, 0 pollution); bug #4 DOCUMENTED.
- Full suite: **12246 passed, 8 failed**. The 8 are ALL `@real_state` real-macOS-keychain
  roundtrips (`test_oauth_rotator.py`×6, `test_safe_storage.py`×2) failing environmentally —
  the machine's live keychain is in the denied/prompting state the USER is cancelling (bug #4's
  own condition: `_live_backup_read()==None`, `StoreResult.FAILED`). NOT a regression (diff is
  100% keepalive; the failing files import no keepalive module; tree clean). Not re-run (would
  spam more keychain prompts). **ORCHESTRATOR publish-gate note:** these 8 may block publish.py's
  test gate until the keychain is unlocked or conftest's `_skip_real_state_when_keychain_prompting`
  probe is hardened (it returned "usable" via a fresh `/usr/bin/security` item yet the real-service
  writes fail — a plugin-test-hygiene gap).
- Full report: `reports/daemon-keepalive-repair/20260709_074731+0200-repair.md`.

## Implementation commits
- `d939110` — fix #1 (init_state resilient to read-only `/`).
- `a39cf84` — fix #2 (staged_is_current whole-closure compare + drop filecmp) + regression test.
