---
trdd-id: EFTQB9RR
title: The disarm opt-out invariant had no writer, and disarm deleted a machine-wide file
column: dev
created: 2026-07-09T20:36:10+0200
updated: 2026-07-09T21:12:00+0200
current-owner: janitor
assignee: janitor
priority: 2
severity: HIGH
effort: M
labels: [fleet, guardian, arm, disarm]
task-type: bugfix
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
impacts: []
attempts: 0
test-failures: 0
last-test-result: pass
last-test-at: 2026-07-09T20:34:00+0200
implementation-commits: [57bfe31, b2be32b, 9e6fa2b]
published-version: 0.36.0
published-at: 2026-07-09T21:05:00+0200
external-refs: ["github.com/Emasoft/ai-maestro-janitor/issues/77"]
---

# The disarm opt-out invariant had no writer, and disarm deleted a machine-wide file

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-09

**This is the NPT of janitor#77 item A.** Item A ("make the armed stamp non-load-bearing")
wants the SessionStart arm-nudge gated on the POSITIVE opt-out `disarmed.flag` rather than on
the presence of `heartbeat-armed-at.ts`. That gate cannot be built until the flag has a
writer. It did not have one.

**PUBLISHED as v0.36.0.** All CI green (Release, CI, zizmor, memgrep binaries, Notify
Marketplace). Deployed to this machine: plugin cache updated 0.35.9 → 0.36.0, the L0
keepalive closure re-staged and byte-verified (`daemon.py`, `lib/fleet_scan.py` sha-match),
daemon restarted (pid 27817). Its first `session-liveness` beat on the new code ran clean —
no `fleet scan failed`, and both stale instances diagnosed `cron_dead` → gentle `rearm`,
which is the honest diagnosis the sweep exists to preserve. Live census: only ONE reachable
project holds a `rate-limited.flag` and it is FRESH, so the sweep correctly deleted nothing.

`column:` stays `dev` deliberately. `complete → publish → published` is a NON-EXEMPT
transition (`~/.claude/rules/manager-approval-defaults.md` §Y), and the same decision is
already pending for TRDD-K3WQ7XM9 (shipped in v0.35.1, still `column: dev`). Both should be
advanced together once the owner rules on it.

- **Bug 1 — `disarmed.flag` had four readers and zero writers.** FIXED (`57bfe31`).
  `/janitor-disarm` now writes it; `/janitor-arm` now removes it, FIRST, before `CronCreate`.
- **Bug 2 — `/janitor-disarm` deleted the machine-wide dispatcher stub.** FIXED (`57bfe31`).
  The `rm -f "${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py"` step is gone, replaced by an explicit
  "do NOT delete this" paragraph naming the blast radius.
- **janitor#77 item A — re-arm on every wake.** FIXED (`b2be32b`). The SessionStart nudge is
  gated on the POSITIVE opt-out instead of the arm stamp. `DISARMED_FLAG` / `RATE_LIMITED_FLAG`
  now live in `state.py` as the single definition.
- **janitor#77 item C — daemon sweep of stale `rate-limited.flag`.** DONE. Pure predicate
  `session_liveness.rate_limit_flag_is_stale`, I/O `fleet_scan.sweep_stale_rate_limit`, wired
  through an opt-in `gather_fleet(sweep_stale_rate_limit_s=…)` so `fleet_status` stays
  read-only; the daemon passes a 24 h window (`rate_limit_flag_max_age_hours`, 0 disables).
- **Tests**: `test_disarm_optout_invariant.py` (5) + `test_stale_rate_limit_sweep.py` (18).
  Full suite 12322 passed, 1 skipped.

**NEXT ACTION:** nothing required. janitor#77 is commented
(`issues/77#issuecomment-4928621347`) with items A and C closed and the two new bugs written
up. Items B and D stay open and are the owner's call.

**Do NOT** bump the CPV pin: `v2.153.1` is the last good ref (`v2.153.2` raises 8 CRITICALs on
our own `rules/*.md` — upstream CPV#160). **Do NOT** re-run `ruff format` on a pre-existing
file: this repo is not format-clean (275 of 308 files would reformat), so it injects ~150
lines of unrelated churn into an otherwise surgical diff. `ruff check` only.

**Load-bearing facts**

- `${CLAUDE_PLUGIN_DATA}` is per-PLUGIN, not per-project:
  `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/`. One `dispatcher-stub.py`
  serves every project's cron. Verified with `ls`.
- `/janitor-disarm` is not only a user command. `dispatch.py:1084` prints a bare
  `[janitor-self-disarm]`, and `rules/janitor-heartbeat-protocol.md` maps that marker to
  "run `/janitor-disarm`". So a `/janitor-global-disarm` makes **every armed session on the
  machine** execute this skill.
- `tests/test_fleet_scan.py:88` writes `disarmed.flag` itself before asserting the `unarmed`
  diagnosis. That is why a missing writer was invisible to the Python suite for its whole life.

**SUPERSEDED — do NOT carry forward**

- `scripts/lib/fleet_scan.py:215`'s docstring: *"only a `disarmed.flag` (written by
  `/janitor-disarm`)"*. It was aspirational, not descriptive, until this TRDD. It is now true.
- `skills/janitor-disarm/SKILL.md`'s old Output/Scope claims ("No files written beyond the two
  removed state files", "does NOT ... touch `.janitor/state/` data"). Both were false of the
  skill that shipped them.

## Problem

### Bug 1 — an invariant asserted by four readers and established by nobody

`disarmed.flag` is the fleet layer's single positive opt-out signal. Four consumers read it:

| consumer | what it does with the flag |
|---|---|
| `fleet_scan.diagnose_root:221` | sets `deliberately_unarmed` |
| `session_liveness.diagnose_instance:217` | `return "unarmed"` — sacrosanct, never touched |
| `fleet_status.py:504` | renders the `unarmed` row + legend |
| `daemon.py:900` | docstring: "a `disarmed.flag` session is sacrosanct" |

Nothing writes it. `grep -rn "disarmed\.flag"` over the whole repo returns four readers, one
test that fabricates the file, and zero writers.

The live consequence is the guardian fighting the user. Run `/janitor-disarm` on a project and
you get: cron deleted, `heartbeat-armed-at.ts` deleted, **no opt-out record**. The next
`session-liveness` beat scans that project, finds no cron and a stale transcript, and
`diagnose_instance` walks past the dead `unarmed` branch to `cron_dead`, whose gentle rung is
`rearm` — which types `/janitor-arm` into the user's pane. The janitor re-arms exactly the
project the user just stopped.

This is bounded today only by how rarely people disarm a single project.

### Bug 2 — a project-scoped command with a fleet-wide blast radius

`/janitor-disarm` step 4 was:

```bash
rm -f "${CLAUDE_PLUGIN_DATA:-...}/dispatcher-stub.py"
```

justified in the skill as *"we just remove the stub so disarm is a clean inverse of arm"*. But
arm's step 1 writes that stub **idempotently to a machine-wide path**. The inverse of a shared
idempotent install is not a delete; it is nothing.

Because `/janitor-disarm` is what a session runs on the `[janitor-self-disarm]` marker, a
`/janitor-global-disarm` has every armed session on the machine reach that `rm` at roughly the
same time. The first session to get there deletes the stub. Every other session's cron then
fires, execs a path that no longer exists, and dies — **before** reaching `dispatch.py`, so it
never emits its own `[janitor-self-disarm]`, never deletes its own cron, and never clears its
`rate-limited.flag`. It fires again five minutes later. Forever.

Each of those fires is a full billed turn (~618k cached-prefix tokens at the 0.1× read rate).
Eliminating exactly that cost is the entire point of TRDD-RQ9FIFX6, which established that a
global stop must make crons *delete themselves* because "only NOT firing costs zero." Step 4
guaranteed that at most one session ever got the chance.

It also compounds with janitor#77 item 1: `/janitor-global-arm` arms nothing, so after a
global disarm the stub stays deleted until somebody runs `/janitor-arm` in some project by
hand.

## Design decisions

**D1 — disarm writes `disarmed.flag`; arm removes it.** The flag becomes what its four readers
already believed it was.

**D2 — arm removes the flag FIRST, before `CronCreate`.** Ordering decides which way a
half-finished arm fails, and every step of a skill can be cut short by a rate limit or an ended
turn. Clearing first means a turn that dies before `CronCreate` leaves *no cron and no opt-out*
→ the guardian reads `cron_dead` → re-arms → self-heals. Clearing last would leave *a cron and
a stale opt-out* → the guardian files the project under "user opted out" and never touches it
again. Failures must fall toward guarded, not toward abandoned. This is the same lesson
janitor#77 item 3 draws about the arm stamp, applied to the flag before the flag can acquire
the same disease.

**D3 — nothing deletes the shared stub.** It is 13 KB, inert without a cron, and
`/plugin uninstall` owns the data dir.

**D4 — the guard test reads the shipped markdown.** The skills *are* the executable artifact —
an agent follows the steps — so the markdown is what must be guarded. Precedent:
`tests/test_memory_recall_shell_snippets.py`, written after an identical class of bug (a
zsh-unsafe snippet that lived in markdown and no Python test could see).
`test_fleet_scan_reads_the_flag_the_skills_write` binds the two halves together: it is the one
assertion that would have caught the original gap, because it fails if either side drifts.

**D5 — the sweep is opt-in at the `gather_fleet` seam, not unconditional.** `gather_fleet` has
two callers: the daemon, and `fleet_status.py`, which renders the read-only `/janitor-show-global-status`
table. A status view that mutates the thing it reports on is a status view nobody can trust, so
`sweep_stale_rate_limit_s` defaults to `None` and only the daemon passes a window. The sweep runs
BEFORE `diagnose_root` for each root, so one beat both clears the litter and acts on the corrected
diagnosis, rather than sweeping now and helping five minutes later. A `disarmed.flag` project is
skipped entirely — sacrosanct means we do not write into its tree, not merely that we do not inject
into its pane.

**D6 — the flag's own mtime is the age.** The StopFailure hook `touch()`es it on EVERY
turn-ending API error, so a session that is genuinely rate-limited right now keeps its flag fresh
for the whole limit and is never swept; a session that has not hit an API error in 24 h is not
rate-limited by any definition. No parsing of `rate-limited-since.ts` is needed (and that file is
misnamed — it is overwritten on every failing turn, so it records the LAST rate limit, not the
first).

## Consequences and follow-ups

- **No migration is possible for already-disarmed projects.** A project disarmed before this
  fix carries no flag and is indistinguishable from a never-armed one. After item A ships, both
  get armed. That is the correct default for a user-scope janitor (`/janitor-arm` step 0
  refuses a non-user install precisely because the janitor guards the whole machine), and the
  user asked for exactly this: *"you should also be sure to have armed all the janitors in all
  projects."* Anyone who wants an opt-out re-runs `/janitor-disarm` once, and it now sticks.
- `fleet_status.py`'s `armed` column keeps meaning "did `/janitor-arm` reach step 6". After
  item A it stops being load-bearing for behavior, but it remains a lying column
  (janitor#77 items 2-3) until #77 item D decides what the table should show.
- **The sweep only reaches projects with a running claude.** `gather_fleet` enumerates the
  process table, so the 17 flagged projects get cleaned when their session next runs. That is
  the complete set of *harmful* cases — `diagnose_instance` is only ever called for a running
  instance, so a flag in a dormant project is inert litter. It is not the complete set of
  *littered* ones.
- **Three fleet options are undeclared in `plugin.json`'s `userConfig`**:
  `session_liveness_enabled`, `fleet_recovery_enabled`, `fleet_hard_restart_enabled`. They are
  read from the environment and work, but no UI surfaces them. Pre-existing gap, noticed while
  declaring `rate_limit_flag_max_age_hours` (which IS declared, matching
  `trashcan_max_age_days`). Worth a separate PR; deliberately not widened into this one.
- **janitor#77 items B and D remain open.** B (fleet-wide arm) needs the ai-maestro server and
  TRDD-VQ4LX7ND's TCC half. D (rename `/janitor-global-arm`) is a naming call for the owner.

## Notes and lessons learned

Both bugs share one shape, and it is the shape of the three mistakes I made earlier today: **a
mechanism asserted in prose and never read to the bottom.** `fleet_scan`'s docstring said the
flag was "written by `/janitor-disarm`" and I had no reason to doubt it — the sentence names a
writer, a reader, and a filename. The way to find out was to grep for the *write*, not to read
the sentence claiming it.

The test suite was complicit. `test_fleet_scan.py` supplies the missing precondition itself
(`(sdir / "disarmed.flag").write_text("")`) and then asserts the reader honors it. Every
assertion passes; the invariant is never established anywhere real. A unit test that constructs
its own precondition can only prove the reader is correct **given** a writer — it says nothing
about whether the writer exists. That is why `test_fleet_scan_reads_the_flag_the_skills_write`
straddles the boundary instead of sitting on one side of it.

And `git log` shows the SKILL.md and `fleet_scan.py` were never touched in the same commit, so
no reviewer ever had both halves on screen at once.
