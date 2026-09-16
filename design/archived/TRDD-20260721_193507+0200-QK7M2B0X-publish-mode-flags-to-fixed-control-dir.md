---
trdd-id: QK7M2B0X
title: Publish the global mode flags to a fixed control dir any daemon can read
column: complete
created: 2026-07-21T19:35:07+0200
updated: 2026-08-05T17:22:57+0200
current-owner: claude-ai-maestro-janitor
task-type: refactor
severity: medium
relevant-rules: [1]
implementation-commits: [9116b22, 627610b, 78879d4, 2b2be24]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-21

**PHASE A SHIPPED in v0.60.0. Phase B NOT STARTED.** Sibling TRDD-5ZVS1DDP (§7.2, one
daemon per host) shipped v0.59.0 and is verified in production against a real server.

**Phase A (done):** `global_state.control_dir()` → the literal `~/.claude/janitor-control/`
(`$JANITOR_CONTROL_DIR` = tests only); the SIX mode flags moved there; readers dual-read
new+old+legacy for the upgrade window; writers write only the new path; CLEAR unlinks all
three. Flag bodies carry `{set_at, by, pid, reason}` while PRESENCE alone still decides, so
a corrupt body can never swallow a kill-switch. Tests: `tests/test_control_dir_flags.py`.

Two defects found while verifying phase A, both silent, both fixed:
`on-session-start.py::_active_global_stop` was reading the flags at their OLD path (a real
machine-wide stop would have stopped being reported at SessionStart); and three test files
were writing the LIVE control plane, because `control_dir()` is fixed by design and does NOT
move when a test sets `JANITOR_GLOBAL_STATE_DIR` — closed by the autouse
`_isolate_control_dir` fixture in `conftest.py`, which must not be removed in favour of
per-file setenv.

**Phase B step 1 — the three coordination LOCKS — SHIPPED.** `marketplace-op`,
`oauth-rotator-tick` and `settings-ensurer` now resolve to `control_dir()`. The transition
is a **dual-LOCK**, not the flags' dual-READ, and that distinction is the whole design: a
flag is data (probe both paths, you cannot miss it), a flock is kernel state on an INODE —
a new-code peer locking only the new path and a 0.60 peer locking only the old one BOTH
win, which is the exact double-`marketplace update` issue #7 exists to prevent. So
`_acquire_dual_flock` holds BOTH inodes for the same critical section, order fixed
NEW-then-OLD, releasing the half it took if the other is contended. Public
`acquire_*_lock()` now returns an OPAQUE handle (a tuple), never a bare fd. Tests:
`tests/test_control_dir_locks.py`. `ticket-dispatch.lock` deliberately did NOT move — no
second owner dispatches a janitor ticket, and the scope rule is AUDIENCE.

**Phase B step 2, SECOND HALF — the SINGLETON — SHIPPED 2026-08-02.** Full suite
14,184 passed / 1 skipped. Column `testing`. All six advisor items landed:

- `_singleton_paths(name)` — ONE dual-era path list (`(era, path)`, NEW-first, realpath-deduped)
  shared by reads, writes AND locks, so the sets cannot disagree. The legacy rung reuses
  `_legacy_read_path`'s predicate, so a WRITE can never resurrect the tombstoned legacy dir.
- `acquire_singleton_dual` / `release_singleton_dual` — holds EVERY era's `daemon.flock`
  NEW-then-OLD; partial hold releases and loses; `blocking=True` preserved for the L0 keepalive
  (`_try_flock` grew the blocking variant). The old single-fd `acquire_singleton_flock` API is
  GONE (grep-verified zero callers). NOT built on `_acquire_dual_flock` — that one releases both
  halves on partial failure; the singleton must hold new ACROSS retirement of old.
- pid/heartbeat DUAL-WRITE (`write_daemon_pid`, `write_heartbeat` → every era) + era-aware reads:
  `read_heartbeat` = max() across eras, `daemon_pid` = LIVE-PREFERRING (a stale pid at one era
  cannot shadow the live daemon at another; stale-vs-absent stays distinguishable).
- Cross-era detector `foreign_era_daemons()` + `daemon._report_foreign_era_daemon` each tick
  (right after the beat — the beat is what made the last double-daemon invisible) →
  `DAEMON-DOUBLE` HIGH finding, per-process deduped.
- Unwritable `control_dir()` → `CONTROL-DIR-UNWRITABLE` HIGH finding via
  `_report_control_dir_unwritable` (once per process per path), wired into `_try_flock` and
  `acquire_singleton_dual`. `_same_file` reused for the same-inode case inside `_singleton_paths`.
- `_MIGRATION_SKIP` += `settings-ensurer.lock`, `ticket-dispatch.lock` (the follow-up folded in).
- Drive-by, same defect class: `fleet_status.py` hand-resolved the LEGACY-era heartbeat/stamp
  paths only (daemon reported DEAD on every migrated/fresh host) → now uses `gs.read_heartbeat()` +
  `gs.read_last_run()`.

Tests: singleton cluster rewritten as BEHAVIOR tests — foreign-PROCESS flock probes (subprocess),
not argv-shape asserts, per the `61252a9` lesson; dual-write/era-read round-trips; live-preferring
pid; `foreign_era_daemons`; old-era holder denies + loser leaks nothing. Mutation-verified: dropping
the old-era half of the hold reds `test_singleton_dual_holds_every_era` +
`test_singleton_dual_loses_to_old_era_holder`. 123 pass in the control-dir cluster, 199 in the
daemon-adjacent cluster.

⚠️ Lesson RE-LEARNED the hard way this session: reverted the mutation with a bare
`git checkout -- <file>` while the real work was still UNCOMMITTED — it wiped the fix along with
the neuter (the `9f7ec64` lesson, verbatim). Re-applied from context. COMMIT BEFORE MUTATING.

**Phase B step 2, FIRST HALF — the `*.last-run.ts` stamps — SHIPPED (`2b2be24`, 2026-08-02).**
`gs.last_run_path()` writes `control_dir()`; `gs.read_last_run()` reads all three eras and takes
`max()`. That read is the OPPOSITE of the flags' first-found, and the difference is the whole
half: during the upgrade window a 0.6x daemon still stamps `global_state_dir()`, so a new-path-only
read sees 0 == "never ran" and re-runs the chore — for `marketplace-refresh` that is the duplicated
bulk `claude plugin marketplace update` issue #7 exists to prevent, re-introduced by the move meant
to make coordination visible. Newest-wins can only DEFER a chore by ≤ its own interval. The
`.failcount` deliberately stayed put (private state; the scope rule is AUDIENCE, not kind) and that
absence is pinned by a test. `daemon_watchdog` keys off `last_run_filename`, not `task_name`, so a
caller whose tag ≠ stem cannot alarm on another chore's stamp. Tests: 6 new in
`test_control_dir_flags.py`; mutation-verified (narrowing the read reds the upgrade-window and
corrupt-stamp cases). Two `test_daemon_bulk_lane.py` assertions moved from the old path to the
public `read_last_run` contract so they survive the singleton move too.

### FABLE-ADVISOR VERDICT 2026-08-02 — PROCEED, but the plan below was INCOMPLETE

Verdict: *"the silent hazard is not the flock, it's the pid/heartbeat READERS."* Verified
first-hand before recording: `daemon_pid()` reads a single `_pid_path()` and `read_heartbeat()`
a single `_heartbeat_path()` — neither dual-reads.

1. **DUAL-WRITE `daemon.pid` + `daemon.heartbeat.ts` to BOTH paths during the window.** This is
   the ROLE INVERSION that makes the singleton unlike the stamps: for stamps the writers were
   old and the readers new, so `read_last_run`'s `max()` fixed it from the reading side. Here the
   writer is NEW and the readers are OLD — a 0.6x session's `daemon_is_alive()` reads only
   `global_state_dir()`, sees nothing, concludes DEAD, and spawn-churns into the held lock.
   Bounded by the crash-loop breaker, but noisy, and invisible from the new daemon's side.
   **Early signal that this was forgotten: `daemon.spawn-history` filling during the upgrade.**
2. **The two-daemon window is AVOIDABLE, not unavoidable.** Non-blocking NEW-then-OLD, exit on
   partial; `daemon_needs_restart`/`_restart_decision` already SIGTERMs a stale-version daemon on
   the first new-code heartbeat, so it closes fast regardless.
3. **Make it DETECTABLE anyway:** each tick, cross-check the OTHER era's `daemon.pid` — a live
   foreign pid ≠ self ⇒ `findings_ledger.record()` + a drift line. Converts a silent
   double-daemon into an indexed finding.
4. **`_try_flock` treats an UNOPENABLE control_dir as HELD** — so an unwritable
   `~/.claude/janitor-control/` means the daemon never starts, silently. That path needs a LOUD
   finding, not a log line. Reuse `_same_file` for the self-deadlock case.
5. **Pointer-file alternative REJECTED.** §7.2's one-daemon-by-CONTENTION needs both parties on
   the SAME inode; a pointer adds foreign parse logic + TOCTOU, and its miss-mode ("pointer
   absent → no lock → run anyway") is exactly the silent-ignore this card exists to kill.
6. **"Hold new across retirement of old" is SOUND** — "retirement" is a code event two releases
   out, not a runtime step. At runtime it is just "hold both fds for the daemon's lifetime",
   which `daemon.py` already does with the 2U8AH82F migration fd. Crash mid-transition is safe:
   flocks die with the process, and a stale pid/heartbeat means respawn.

**Recommended primitive:** `acquire_singleton_dual(blocking=...)` — non-blocking NEW-then-OLD,
exit/wait on partial, fds never released (a blocking variant is deadlock-free because the
acquisition order is total). NOT `_acquire_dual_flock`, which releases both halves on partial
failure.

**NEXT ACTION (testing):** OBSERVE one real daemon generation-handoff on this host after the
next release rolls (old daemon SIGTERM'd by `daemon_needs_restart`, new one acquires the dual
singleton, `DAEMON-DOUBLE` stays absent from the ledger, `daemon.spawn-history` does NOT fill).
After that, chore migration (`cache-prune`, `rules-cleanup`, `github-config-audit`,
`memory-guard` → per-repo heartbeat) unblocks, and the transitional fallbacks retire two
releases out (step 5).

**Follow-up noticed while moving the locks (not done, deliberately out of step 1):**
`_MIGRATION_SKIP` names only `marketplace-op.lock` and `oauth-rotator-tick.lock`, so
TRDD-2U8AH82F's legacy→DATA copy still copies `settings-ensurer.lock` and
`ticket-dispatch.lock` — harmless (an empty file conveys no kernel state) but contrary to
that set's own stated invariant. Fold it into the singleton step, where migration code is
already being touched; do not touch migration for cosmetics alone.

Copy phase A's pattern verbatim (dual-read on read, single-write on write, clear from ALL
locations). Chore migration (`cache-prune`, `rules-cleanup`, `github-config-audit`,
`memory-guard` → per-repo heartbeat) is gated on the locks landing — moving a chore to the
cron before its lock is shared IS the corruption case.

**SUPERSEDED — do NOT carry forward** (phase A shipped it; kept only so a reader who
remembers this directive knows it is done, not dropped): add `global_state.control_dir()` returning the literal
`~/.claude/janitor-control/` (honoring `$JANITOR_CONTROL_DIR` for tests only), repoint the
COORDINATION set at it (see the scope rule below — NOT just the six mode flags), and give
each reader a transitional dual-read of the old location.

**SCOPE CORRECTED 2026-07-21 (owner directive, after the first draft):** *"make sure all
global flags written by the daemon are written in the same folder, so the ai-maestro
server daemon and the normal daemon process can both share it and always be in synch."*
The first draft moved only the six mode flags. That was too narrow and would have left the
two daemons desynchronised on the very things §2 relies on — see "What moves" below. The
LOCKS are the load-bearing addition: a lock excludes only processes contending on the SAME
file, so a server locking a path the janitor never opens excludes nobody.

**Load-bearing facts, verified 2026-07-21:**

- The six flags and their current helpers in `scripts/lib/global_state.py`:
  `kill-switch.flag` (:241), `reload-needed.flag` (:253), `skills-reload-needed.flag`
  (:257), `maintenance-mode.flag` (:340), `global-pause.flag` (:376),
  `version-update-requested.flag` (:422). Each is `global_state_dir() / "<name>"`.
- `maintenance_mode_present` (:354), `kill_switch_present` (:317) and
  `global_pause_present` (:387) ALREADY carry a `_legacy_read_path(...)` dual-read from
  TRDD-2U8AH82F. This move adds a second transitional source, so keep the dual-read
  helper generic rather than writing a third bespoke fallback per flag.
- ⚠️ **STALE as written — superseded by the SCOPE CORRECTION above, and by what has since
  shipped.** It said: *"`global_state_dir()` keeps its four-rung ladder for everything else —
  pid, flock, heartbeat, last-run stamps, injection stamps, the migration marker. Only the MODE
  flags move."* That was the FIRST DRAFT's narrow scope, written before the owner widened it the
  same day. Since then the three LOCKS (step 1) and the LAST-RUN STAMPS (step 2 first half,
  `2b2be24`) have both moved, and the singleton is explicitly the next step — so three of the six
  things this bullet lists as staying have moved or are scheduled to.
  **What actually stays:** the `.failcount` (private streak), the injection stamps, and the
  migration marker — none of which a second chore owner reads. The rule that decides is AUDIENCE,
  not kind. Still true and still load-bearing: **do not "simplify" by moving the whole dir** —
  `global_state_dir()`'s ladder exists for state a foreign reader has no business resolving.

## Why

Owner directives, 2026-07-21: *"all global states must be shared via a file-flag. just
write to it, and whichever daemon is on will read it and switch the mode accordingly"* and
*"put it under some standard janitor folder."*

The flags already are files, and the janitor already reads them correctly. What blocks a
foreign reader is WHERE they are: `global_state_dir()` resolves through
`$JANITOR_GLOBAL_STATE_DIR` → `$XDG_STATE_HOME/janitor/` → the plugin DATA dir → the
legacy dir. An ai-maestro server cannot reproduce that safely — and the failure is silent
in the worst direction. A server that hardcodes the DATA path and runs on a host where
`XDG_STATE_HOME` is set (a normal Linux desktop) stats a file that never exists, reads
"no maintenance", and keeps running chores through a fleet-wide maintenance nobody can
see. A control plane whose miss-mode is "looks fine, ignores the flag" is worse than none.

## The design (ARCHITECTURE.md §7.1)

Split by audience, NOT a reversal of TRDD-2U8AH82F:

**What moves — the scope rule is AUDIENCE, not kind:** if a SECOND chore owner must
observe it or contend on it, it moves.

| dir | holds | lifecycle |
|---|---|---|
| `~/.claude/janitor-control/` (new, FIXED) | the six MODE flags · the three coordination LOCKS (`marketplace-op`, `oauth-rotator-tick`, `settings-ensurer`) · the per-chore `*.last-run.ts` stamps · the daemon singleton (`daemon.pid`, `daemon.flock`, `daemon.heartbeat.ts`) | ephemeral control; SHOULD vanish on uninstall — a removed janitor must not leave a flag claiming the host is in maintenance, nor a lock nobody will release |
| `<DATA>/global-state/` (unchanged) | `recovery-audit.ndjson`, token-attribution cache, `migrated-from-legacy.ts`, fleet injection stamps, `daemon.spawn-attempt.ts` | private state, no second reader; durability is a virtue here, so the DATA principle still governs |

Why each addition beyond the mode flags:

- **Locks** — §2 names them the collision backstop for the 90 s handoff window. `flock(2)`
  excludes only processes holding the SAME file, so a lock the server cannot see excludes
  nobody and the backstop silently does nothing. Cross-language is fine: `flock` is an OS
  primitive, not a Python one.
- **`*.last-run.ts`** — without a shared stamp neither owner can tell the other "already
  done at T", so both redo the chore inside the handoff window. That is exactly the
  duplicate work §2 exists to prevent.
- **The singleton (`daemon.pid`/`daemon.flock`/`daemon.heartbeat.ts`)** — makes §7.2's
  one-daemon-per-host enforceable by CONTENTION, not merely by polling a liveness file
  with a 90 s window. **Carries TRDD-2U8AH82F's flock-moves-LAST invariant:** take the new
  lock BEFORE retiring the old, or the upgrade opens a two-daemon window — the precise bug
  that migration was designed to avoid.

### Flags MUST carry provenance (added 2026-07-21, from a live incident)

Observed this session: `maintenance-mode.flag` was found SET, mtime 19:07:22, content the
bare default `"maintenance"`. Local maintenance was absent, so every fire in this session
was being suppressed machine-wide. **The writer could not be determined** — not from the
content, not from any log, not from any audit record. The candidate tests were exonerated
by an mtime probe (a run of all five maintenance-touching test files left the mtime
untouched), which narrowed nothing, because there is no record to narrow toward.

This is the mechanism behind the owner's original complaint earlier the same day: the
plugin did not auto-update because the daemon's `version-update` task was idled by
maintenance, while `daemon.heartbeat.ts` kept advancing — so the daemon looked alive and
healthy. Daemon-alive is not daemon-running-chores, and nothing on screen said which.

So the control plane's file format is not "presence, content advisory". Each flag MUST be
written as one line of JSON carrying at minimum:

```json
{"set_at": 1784653642, "by": "global_control_cli.py maintenance", "pid": 54451, "reason": "<free text>"}
```

- **Readers still key on PRESENCE only** — a malformed or unparseable body must still mean
  "flag is set" (fail-safe: never ignore a stop signal because its metadata is corrupt).
  Provenance is for humans and diagnostics, never for the switching decision.
- `/janitor-show-global-status` and the arm's `maintenance=global-on` line report `by` and
  `set_at`, so "who put this host in maintenance and when" is answerable without forensics.
- Applies to every flag in the vocabulary, not just maintenance — a `kill-switch.flag`
  with no author is the same problem with a bigger blast radius.

Backward compatibility: a legacy flag whose body is not JSON is still SET, reported with
`by: unknown`. That is precisely today's state and must not crash a reader.

TRDD-2U8AH82F moved STATE into DATA and was right to; this publishes CONTROL and does not
touch that. The standing "prefer `${CLAUDE_PLUGIN_DATA}` over a custom `~/.claude/` folder"
principle keeps governing state — its stated reasons (survives updates, backed up, cleanly
purged) are all about durability, which is the property a mode flag must NOT have.

Steps:

1. `global_state.control_dir()` — literal `~/.claude/janitor-control/`, `$JANITOR_CONTROL_DIR`
   override for tests only, created on demand.
2. Repoint the COORDINATION set (mode flags, locks, last-run stamps, singleton) at it.
   Writes stay atomic (tmp + `os.replace`). Do the singleton LAST and flock-moves-LAST
   within it, per TRDD-2U8AH82F — the mode flags and stamps are safe to move in any order
   because a mis-timed read only costs one duplicated chore, whereas a mis-timed flock move
   costs a second daemon.
3. Transitional dual-read: each presence check falls back to the old
   `global_state_dir()/<name>` so a running daemon from the previous version and a session
   from the new one agree during the upgrade window. Writers write ONLY the new path.
4. `rules-cleanup` (or the uninstall path) removes `~/.claude/janitor-control/` when the
   janitor is confirmed uninstalled — the flags must not outlive the plugin.
5. Retire the transitional fallback two releases out, as TRDD-2U8AH82F's own legacy
   fallback is being retired.

## Verification

- Unit: each flag round-trips through the new dir; `$JANITOR_CONTROL_DIR` redirects it.
- Unit: a flag present ONLY at the old path is still seen (the upgrade window), and a
  writer never recreates the old path.
- Unit: `control_dir()` ignores `$XDG_STATE_HOME` and `$JANITOR_GLOBAL_STATE_DIR` — the
  whole point is that it does not move.
- Unit: the PRIVATE set (`recovery-audit.ndjson`, token cache, migration marker, injection
  stamps, spawn-attempt ring) is UNCHANGED and still ladder-resolved.
- Concurrency: two processes contending on the moved `marketplace-op.lock` still serialise
  — the lock must exclude across the new path, which is the entire reason it moved.
- Upgrade window: an old-path holder and a new-path holder must NOT both believe they hold
  the singleton. Test the flock-moves-LAST ordering explicitly, not just the end state.
- Integration: set maintenance, stat the literal `~/.claude/janitor-control/maintenance-mode.flag`
  with no janitor code involved — that is the contract a foreign reader gets.
- Full `uv run pytest` + `ruff check` green before any commit.

## Notes and lessons learned

[^1]: [id:ATOM-QK7M-0001, status:valid, keywords:"external_consumer_hardcodes_path resolution_ladder_silent_miss XDG_STATE_HOME_moves_dir flag_read_returns_false", ocd:2026-07-21, lmd:2026-07-21]
  DO NOT publish a cross-process contract on a path that resolves through a ladder,
  BECAUSE a foreign reader can only hardcode one rung and every other rung then makes it
  read a file that does not exist — which returns "flag absent", i.e. it silently ignores
  the control plane instead of failing loudly. DO give an external contract a literal
  fixed path, and keep ladder-resolved locations for state only this plugin reads.

[^2]: [id:ATOM-QK7M-0002, status:valid, keywords:"lock_moved_to_new_path dual_lock_self_deadlock same_inode_opened_twice chore_skips_forever flock_across_open_descriptions", ocd:2026-07-22, lmd:2026-07-22]
  DO NOT hold a migrating lock at BOTH its old and new path without first checking they
  are the same file, BECAUSE flock(2) conflicts across independent open file descriptions
  even inside ONE process, so when the two dirs coincide the second open denies you your
  own lock and the chore skips FOREVER while logging as ordinary contention. DO compare
  `os.path.realpath` of both paths first and lock a single inode once.
