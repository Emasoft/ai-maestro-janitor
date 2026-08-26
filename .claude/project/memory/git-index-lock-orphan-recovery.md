---
name: git-index-lock-orphan-recovery
description: "git hangs forever on .git/index.lock / a commit is refused with live-git but no git is running / the stale-lock detector never removes anything / index.lock left behind by a killed commit / my guard reads UNKNOWN under parallel test load / os.kill(pid,0) says alive but the process is a corpse"
ocd: 2026-08-26
lmd: 2026-08-26
metadata:
  node_type: memory
  type: project
  tier: component
publish-globally: false
---

# git-index-lock-orphan-recovery


^ATOM-KJG1-030H [desc: "orphaned index.lock recovery: prevention covers the reader, recovery covers the dead writer; every guard fails closed", keywords: git_hangs_forever_on_index.lock a_killed_commit_left_a_lock_behind every_git_write_stalls_and_nothing_times_out who_removes_a_stale_.git/index.lock GIT_OPTIONAL_LOCKS stale-index-lock_detector, ocd: 2026-08-26, lmd: 2026-08-26]

A killed `git commit` leaves `.git/index.lock` behind with nobody to release it, and every later git write then stalls INDEFINITELY (it blocked a live session for hours on 2026-08-14). Prevention was already in place and cannot cover this: `GIT_OPTIONAL_LOCKS=0` on every read-only call site — enforced by an AST drift guard, because `git status`/`git diff` write the lock for an optional stat-cache write-back even on a pure read — stops a detector STEALING the lock, but nothing stops a WRITER dying mid-write. The recovery half is `scripts/lib/git_utils.clear_stale_index_lock` plus the `stale-index-lock` heartbeat detector that calls it (registered in the dispatch cadence table and `_ADVISORY_DETECTORS`). All of its guards are FAIL-CLOSED, because the only real danger is removing a lock a live process still holds — which means every bug in this subsystem shows up as a REFUSAL TO RECOVER, never as a wrongly-removed lock. Landed dc1af1ed (janitor#245), then fixed four times: 440e859c, 7894e6e2, 8e4a5413 (TRDD-TUWUB0SG), 1a4ea9e6. [^1] [^2]

## Governed by

- [[janitor-architecture]] — the architecture hub.
- [[memory-system]] — cites this page for the same "a correct mechanism that never
  reaches its case" shape, there caused by the PROJECT scope gate.

## Notes and lessons learned

[^1]: [id: ATOM-Q16I-GBMG, status: valid, desc: "liveness is not holding — the same fail-closed defect landed three times from three directions", keywords: "commit_refused_with_live-git_but_no_git_is_running the_stale-lock_detector_never_removes_anything my_guard_blocks_on_a_pid_that_already_exited os.kill_says_alive_but_the_process_is_a_corpse lsof_returned_no-probe_under_test_load a_guard_that_always_refuses fail-closed_guard_never_fires", ocd: 2026-08-26, lmd: 2026-08-26] DO NOT gate a fail-closed recovery on "is a process alive?", BECAUSE liveness is not holding: three of this subsystem's four post-ship fixes were the SAME defect in different dress — an EXITED git still listed in a `ps` still-photograph (440e859c), a ZOMBIE that `os.kill(pid,0)` reports alive because the kernel keeps its exit slot while `lsof` can resolve no cwd (1a4ea9e6), and a real fd-holder that read UNKNOWN because a 5 s `lsof` timeout had no margin under a 16-way xdist run (7894e6e2). Short-lived git invocations are CONTINUOUS on a busy host, so their corpses are too, and the recovery became refusable at random — "a guard that always refuses is equivalent to no guard", reached three times from three directions. DO gate on evidence of HOLDING (an fd, a resolvable cwd), give the primary probe real margin rather than loosening the test that caught it, and make each sub-guard fail closed in ITS OWN direction — `_pid_is_zombie` answers False on any probe failure, so an unreadable process state can never be what AUTHORISES a removal. Watch for the symptom, since fail-closed hides it: a refusal naming a pid that is already gone.
[^2]: [id: ATOM-PHYB-DMOE, status: valid, desc: "a fail-closed subsystem has no incidents to trigger on, so a commit-count nudge is its only signal", keywords: "is_the_memorize-nudge_worth_acting_on commit_frequency_is_a_crude_proxy_for_needing_a_note why_did_a_nudge_fire_on_a_subsystem_with_no_incidents a_quiet_subsystem_has_no_bugs_to_report should_I_ignore_this_memory_nudge", ocd: 2026-08-26, lmd: 2026-08-26] DO NOT dismiss `memorize-nudge`'s commit-frequency trigger as a crude proxy for "this needs a memory note", BECAUSE for a FAIL-CLOSED subsystem it is the only signal that can exist: such a subsystem cannot accumulate visible incidents — its bugs present as refusals that read as caution working, so there is no outage, no error report and no user complaint to trigger on — and commit frequency is what remains. This page exists because the nudge fired on 7 commits in 14 days here; nothing else on the machine would have asked for it. DO treat a nudge on a quiet-by-construction subsystem as HIGHER signal than one on a noisy subsystem, not lower (observation from the ai-maestro hub, 2026-08-26, their 2167386a; the inverse failure — the nudge gating on WHEN a note was last written rather than WHAT was uncaptured, falling silent while seven commits of mechanism went unrecorded — is on [[claude-md-canonical-form]]).
