---
name: janitor-keepalive-test-isolation-fsevents
description: "a unit test wrote to the REAL ~/.claude/janitor-global-state or the real plugin DATA dir / a test polluted production state / MY COMMITTED WORK WAS SILENTLY REVERTED / the repo's scripts/ got overwritten with the released version / files reverted to an old release with the exec bit cleared / PermissionError running scripts/daemon.py in tests / the janitor drove fseventsd to 39GB and crashed the machine / how to isolate janitor global-state + DATA in tests / how to stop a test writing outside its boundary / a module-level Path.home() constant froze the dir at import so monkeypatch(HOME) never reached it / why the L0 keepalive restage churns the filesystem / JANITOR_GLOBAL_STATE_DIR + JANITOR_DATA_DIR isolation levers (NOT CLAUDE_PLUGIN_DATA) / a test wrote the LIVE control plane and JANITOR_GLOBAL_STATE_DIR did not move it / a kill-switch flag appeared from nowhere and disarmed the fleet / how to root-cause an fseventsd or mds RAM/CPU runaway"
ocd: 2026-07-03
lmd: 2026-07-22
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

## The RECURRENCE (TRDD-RYZCVVKA, 2026-07-11) — same gate, new victim: the SOURCE TREE

The ZNN0UK5K fix held for the tests, but the same `verify_or_restage → _repair →
stage_closure` gate had a second mouth. `daemon_keepalive_entry.py` calls
`verify_or_restage(_HERE)` — **its own directory**. So executing the **repo's** copy of the
entry makes the gate compare the REPO against the installed CACHE, judge the newer committed
code "corrupt/incomplete", and "repair" it by **overwriting the working tree with the released
version** — silently reverting committed work. Exec bits die too (`stage_closure` writes a
fresh tmp at the 0644 umask, then `os.replace`s), and that lost `+x` is the ONLY reason it was
noticed: 22 tests began failing with `PermissionError: .../scripts/daemon.py`.[^2]

**How it was proven** (the artifacts were on disk the whole time): the LAST line of
`global-state/daemon-keepalive.boot.log` names the restage source (`…/cache/…/0.39.0/scripts`),
and the sibling `daemon-keepalive.restage-stamp` carries the epoch **and the mismatch list** —
which was exactly the set of files the repo had changed since that release. Timestamp and file
list both match the clobber to the second.

**The fixes (three layers, because every OPT-IN layer here has been escaped at least once):**

1. **Refuse the write** (`fef258c`): `keepalive_stage.stage_closure` raises
   `UnsafeStageDestination` when the destination is inside a plugin SOURCE checkout (a git work
   tree whose root carries `.claude-plugin/plugin.json`). The closure only ever belongs in the
   DATA dir, so a repo destination is ALWAYS a bug. The predicate is deliberately narrow —
   "inside any git repo" would refuse the LEGITIMATE production stage for anyone keeping `~` or
   `~/.claude` in a dotfiles repo, silently killing the L0 keepalive.
2. **A HARD WRITE SANDBOX in `tests/conftest.py`** (`05b1a38`, layer S1e): `pytest_configure`
   wraps the write syscalls — `builtins.open`, **`io.open`**, `os.open`,
   `replace`/`rename`/`symlink`/`link`, `remove`/`unlink`/`rmdir`/`mkdir`/`makedirs`/`chmod`/
   `truncate`, and `shutil.rmtree` — and RAISES `SandboxViolation` on any write into the real
   `~/.claude` tree or the repo source. **Not a fixture**: nothing to opt into, nothing to
   forget.[^3]
3. **Manifest guards must re-snapshot with the SAME function** that built the baseline. The S1c
   source-tree guard compared a `*.py`/`*.sh`-scoped BEFORE against an unscoped AFTER, so 15k
   vendored Rust artifacts read as "ADDED" and would have drowned every real signal.

**Sandbox implementation traps** (both bit while writing it; both caught by the positive
controls in `tests/test_write_sandbox.py`, which is the whole argument for proving a guard
fires rather than trusting its docstring):
- **`io.open` is a SEPARATE binding from `builtins.open`.** `pathlib.Path.open` (hence
  `write_text`/`write_bytes`) calls `io.open`, so patching only builtins lets every pathlib
  write straight through. Patch both.
- **For `os.replace(src, dst)` the file DESTROYED is `dst`.** Guarding `src` polices the
  harmless tmp file and waves the clobber through — it overwrote `scripts/daemon.py` a SECOND
  time, mid-fix.
- **Honor `dir_fd`.** `shutil.rmtree` walks with `os.rmdir("design", dir_fd=…)` — a BARE
  relative name. Resolving it against the cwd makes a `TemporaryDirectory` cleanup look like an
  attack on the real `design/` (it failed 68 innocent tests). Skip fd-relative calls and guard
  `rmtree` at its ENTRY POINT instead, which is what actually bounds the recursive delete.

## See also

- [[janitor-architecture]] — the L0–L3 immortality layers this component lives in.
- [[macos-keychain]] — the 2026-07-09 keychain-flood RECURRENCE: this keepalive had STAGED the
  pre-fix 0.31.0 flooder into DATA and kept relaunching it, so a published+cached fix never
  reached the running daemon until the staged closure was force-restaged + byte-verified (that
  page's root-cause #5 / lesson `[^2]`).
- Same keepalive subsystem, related seam: the hub's TRDD-KEEPQRTN lesson (`[^3]`) —
  "a self-healing gate must be consulted by EVERY respawn path." Both are keepalive
  restage/respawn bugs that looked correct per-path but broke at the whole-surface
  seam.

^control-dir-ignores-the-isolation-lever [desc: fixed_path_defeats_env_isolation, keywords: test wrote the live control plane JANITOR_GLOBAL_STATE_DIR did not move it kill-switch leaked from a test autouse _isolate_control_dir fixture, type: project, ocd: 2026-07-22, lmd: 2026-07-22]
`control_dir()` (the `~/.claude/janitor-control/` control plane, TRDD-QK7M2B0X) is
deliberately a LITERAL fixed path with no resolution ladder — that is its whole purpose, so
a foreign reader like the ai-maestro server can hardcode it. The consequence for tests is
that it does **not** move when a test sets `JANITOR_GLOBAL_STATE_DIR`: the established
isolation lever silently covers everything EXCEPT the flags with the widest blast radius.
Three test files were writing the LIVE control plane before this was noticed; a leaked
`kill-switch.flag` disarms the whole fleet. The fix is the **autouse `_isolate_control_dir`
fixture in `tests/conftest.py`** — autouse, not per-file `setenv`, because the failure mode
is a test nobody remembered to opt in. Do not remove it or "simplify" it back to per-file. [^4]

## Notes and lessons learned

[^1]: [id:ATOM-MG07-0010, status:valid, keywords:"test_isolation_defect_corrupted_real_state frozen_path_home_vs_monkeypatch_setenv env_change_after_import_constant", ocd:2026-07-03, lmd:2026-07-03] The keepalive tests had polluted the real
  boot log for weeks (pytest paths visible in the production
  `daemon-keepalive.boot.log`) before it cascaded into an OS crash — a
  test-isolation defect is not "just a test smell"; here it corrupted real staged
  state and took down the host. The tell: a *frozen* `Path.home()` module constant
  vs a test that only `monkeypatch.setenv("HOME", …)` — the env change lands AFTER
  the constant was already computed at import, so the two never meet. Verified fix +
  proof: janitor suite `pytest tests/` = 12028 passed AND `find
  ~/.claude/janitor-global-state -newermt "25 minutes ago"` empty during the test
  run (real state untouched).
[^2]: [id:ATOM-MG07-0011, status:valid, keywords:"self_heal_weapon_wrong_directory verify_or_restage_source_checkout refuse_illegal_destinations_at_write", ocd:2026-07-11, lmd:2026-07-11] **A self-heal is a WEAPON pointed at whatever directory it
  is handed.** `verify_or_restage(_HERE)` was written to keep the DATA stage honest; nobody asked
  what it does when `_HERE` is a source checkout, and the `_repair` else-branch even carried a
  comment blessing that case ("keeps the gate self-consistent if ever invoked from a non-DATA
  dir"). It restores files to the CACHED release, so aiming it at a repo means "revert all
  uncommitted-to-release work". Lesson: for any restore/self-heal/sync, enumerate the
  destinations it can legally have and REFUSE the rest at the write — an authoritative source
  overwriting a "corrupt" target is indistinguishable from vandalism when the target is actually
  the newer thing.
[^3]: [id:ATOM-MG07-0012, status:valid, keywords:"opt_in_test_isolation_fails_silently exclusion_hides_its_own_incident experiment_after_fix_proves_fix_not_innocence", ocd:2026-07-11, lmd:2026-07-11] **Opt-in test isolation fails silently and forever.** THREE
  layers here each claimed to stop tests touching real state (per-module `_isolate_janitor_state`
  fixtures, the S1a session-default env redirect, the S1b/S1c manifest guards) — and the REAL
  `daemon-keepalive.boot.log` still held 432 lines of which **296 name a pytest tmp dir** as the
  restage source. Worse, S1b EXCLUDED `.log` and `.restage-stamp` as "daemon liveness churn" —
  the exact two files this incident wrote, so the detector was blind to its own incident. Lessons:
  (a) an exclusion added to silence noise must be interrogated for the failure class it makes
  invisible; (b) only refusing the write at the SYSCALL, with no opt-out, actually holds; and
  (c) I first "EXONERATED" the suite by instrumenting a run that happened AFTER the guard refusing
  the write had landed — **an experiment run after the fix proves the fix, never the innocence of
  the suspect.** Reconstruct an incident from artifacts written AT THE TIME (the boot log and
  restage-stamp were sitting on disk the whole time; I asserted they were stale without opening
  them).
[^4]: [id:ATOM-MG22-0001, status:valid, keywords:"env_isolation_lever_missed_a_fixed_path test_wrote_the_live_control_plane autouse_fixture_not_per_file_setenv", ocd:2026-07-22, lmd:2026-07-22]
  DO NOT assume an established env isolation lever (`JANITOR_GLOBAL_STATE_DIR`) covers every
  state path, BECAUSE `control_dir()` is fixed BY DESIGN and does not move — three test files
  wrote the live control plane, where a leaked `kill-switch.flag` disarms the fleet. DO isolate
  a fixed path with an AUTOUSE fixture (`_isolate_control_dir`), never per-file `setenv`.
