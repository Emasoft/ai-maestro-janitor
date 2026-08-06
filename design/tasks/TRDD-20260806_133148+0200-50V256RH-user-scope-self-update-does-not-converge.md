---
trdd-id: 50V256RH
title: The janitor does not converge itself to the latest version at user scope — sessions run stale code for a day while the fix sits cached
column: dev
created: 2026-08-06T13:31:48+0200
updated: 2026-08-06T18:45:00+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
scope: project
severity: high
relevant-rules: []
implementation-commits: []
---

# User-scope self-update does not converge (owner failure report 2026-08-06, item 5)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-06

**Root cause FOUND and PROVEN. It is not the one the body hypothesizes.** No code change yet —
the fix moves a global-state write, which is an ownership decision (see NEXT ACTION).

### The body's hypothesis is DISPROVED

It asks *"did the server (claim-holder) run `user-plugins-update`/`version-update` at all?"*
**It did — twice, within the last two hours.** Measured live 2026-08-06:

```
version-update      ran   106 min ago
user-plugins-update ran   102 min ago
reload generation stamped 729 min ago   <-- STALE: predates the update by ~10h
```

And the pin IS converged: cached/running `2.4.1` == latest published `2.4.1`, install scopes
`['user','local']`. So "the pin does not converge" is **not** the defect.

### THE ACTUAL ROOT CAUSE

**The reload stamp is a side-effect of the janitor daemon's update TASK BODY, not of the update
EVENT.** Every writer of the reload generation lives in `scripts/daemon.py` — and nowhere else:

```
scripts/daemon.py:484   gs.set_reload_flag(",".join(updated_ids[:10]))
scripts/daemon.py:528   gs.set_reload_flag(f"janitor-self-update@{new_latest}")
scripts/daemon.py:2067  gs.set_reload_flag(f"plugin-update@{plugin_id}")
```

When a live ai-maestro server absorbs the update chores — the documented, CORRECT hand-off
(`[[claude-code-plugin-rollout-staleness]]` `ATOM-14GY-NESV`) — the janitor daemon stands down,
so **the only code that stamps the reload generation is the code that just stood down.**
Verified live: `server_is_alive=True`, `server_runs_chores=True`,
`claimed_chores=['marketplace-refresh','oauth-rotator-supervisor','oauth-rotator-tick',
'user-plugins-update','version-update']`.

Consequence: **the CACHE converges and the RUNNING SESSIONS never do.** No `[janitor-reload]` is
ever emitted, so every live session keeps executing the plugin version it loaded at start — which
is exactly the owner's symptom (2.3.0 skills invoked all day while 2.4.1 sat cached, including
the retired `USER_PRESENT` presence-cancel whose fix was already published). Nothing errors
anywhere, because nothing is watching.

This SHARPENS `ATOM-14GY-NESV` rather than repeating it: that atom covers "the server never
consumes the request". Here the server DID consume it, promptly and correctly — and the machine
still ran stale code.

### NEXT ACTION (one step, runnable) — needs an ownership decision first

Stamp the reload generation from the **OBSERVATION that the version changed**, not from the
ACTION that changed it: a beat that compares the running/installed version against the cached
latest and stamps `set_reload_flag` when they differ, **regardless of who performed the update**.

The decision I will not take unilaterally: **where that writer lives.** The daemon is the
single-writer of global state by design, but the daemon is precisely what stands down here. The
two candidates —
1. the daemon's **chore-coordination path** (it already knows it YIELDED — stamp on observed
   version change rather than inside the skipped task body); or
2. a **per-session detector** (runs regardless of any claim, but multiplies writers of a
   global-state file, weakening the single-writer invariant).

Overlaps TRDD-6CRC9SQQ (the delegation contract) — the card itself assigns
"watchdog on a SERVER-claimed chore" to that sibling. Resolve the boundary before coding.

### Verified (do not re-verify)

- `set_reload_flag` has exactly THREE call sites, all in `scripts/daemon.py` (grep, whole tree).
- Chore stamps, claim state and pin/latest all read live via `global_state` / `harness_backend` /
  `version_update_lib` — numbers above are measurements, not inference.

## WHY (measured today)

This session invoked 2.3.0 skills ALL DAY while 2.4.1 sat cached: the retired
`USER_PRESENT` presence-cancel fired from the 2.3.0 `clear_trigger.py` even though 2.4.1
ships the ratified defer-retry chain — the owner hit the exact bug whose fix was already
published. Daemon log, same morning: `chore-coordination: yielding to active ai-maestro
server: [... 'user-plugins-update', 'version-update']` — the SELF-UPDATE chore was
delegated via the claim handshake, and nothing on either side converged the janitor's
user-scope pin or drove the reload/re-arm chain to completion. Also found: harness-agent
workdirs still pinned at **0.60.1** at local scope in the install registry.

## The task (make convergence END-TO-END, not best-effort)

End state after a release: within one daemon cadence, EVERY scope's pin is the latest
version, the reload generation is stamped, every live session consumes
`[janitor-reload]`, and the cron is re-armed iff the stub path/cadence changed. No human
action, no session left running superseded code for hours.

1. Root-cause today's non-convergence: did the server (claim-holder) run
   `user-plugins-update`/`version-update` at all? Did the janitor's own yielded chores
   have a watchdog on the claim-holder's completion stamps? (`daemon_watchdog.
   emit_if_daemon_stale` covers OUR daemon; nothing watches a SERVER-claimed chore —
   that half belongs to TRDD-6CRC9SQQ.)
2. Add the missing verification rung: after any janitor self-update lands, verify the
   RUNNING surfaces converged (pin == latest, reload acked per project, armed stub
   current) and re-signal until they do — convergence is a loop with a proof, not a
   one-shot update command.
3. Sweep the stale local-scope pins (0.60.1-era) in agent workdirs, or explicitly
   document why local pins are the harness's to manage.

## Acceptance

- [x] today's non-convergence root-caused — the SERVER held the claim and **did** run both chores
      (106/102 min ago); the defect is that `set_reload_flag` lives only in the daemon task bodies
      the daemon skips when it yields, so the CACHE converged and the SESSIONS never did
- [ ] ~~a convergence check that FAILS LOUD when installed != latest~~ — **wrong predicate**:
      installed == latest == 2.4.1 during the incident. Replaced by: **fail loud when the reload
      generation is OLDER than the newest update-chore completion stamp** (measured gap: 729 min
      vs 106 min), which is the condition that was actually true
- [ ] observed: next release reaches pin+reload+arm on this host with zero human action
- [ ] stale 0.60.1 local pins resolved or ruled out-of-scope in writing

## Pointers

- Version-skew incidents this session: retired USER_PRESENT (2.3.0 vs 2.4.1);
  yesterday's [version-update] advisory recommending re-arm onto a quarantined version
  (janitor#211 thread).
- Memory: [[claude-code-plugin-rollout-staleness]] ("the fix is published but the bug
  keeps happening").
- Siblings: TRDD-6CRC9SQQ (delegation alignment), TRDD-AR9IUGIJ (kill the re-arm need).
