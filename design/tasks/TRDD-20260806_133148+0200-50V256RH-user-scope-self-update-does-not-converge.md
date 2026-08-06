---
trdd-id: 50V256RH
title: The janitor does not converge itself to the latest version at user scope — sessions run stale code for a day while the fix sits cached
column: dev
created: 2026-08-06T13:31:48+0200
updated: 2026-08-06T19:02:00+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
scope: project
severity: high
relevant-rules: []
implementation-commits: []
---

# User-scope self-update does not converge (owner failure report 2026-08-06, item 5)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-06

**Root cause NOT yet established.** My first answer was published and then DISPROVED by its own
evidence — see the withdrawal below. The verified timeline stands; the conclusion does not.

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

### ⚠ WITHDRAWN — my first root cause was WRONG (recorded, not deleted)

I published: *"the daemon stands down for the server-claimed update chores, so `set_reload_flag`
— which lives only in those task bodies — never fires."* **The premise is unsupported and the
conclusion is false.** What was true: all three `set_reload_flag` call sites really are in
`scripts/daemon.py` (484, 528, 2067), and `claimed_chores()` really does list
`user-plugins-update` + `version-update`. What I never checked before concluding: **the daemon's
own log.** It shows the daemon RAN `version-update` (16:35:59), and there is **not one
`yielding to active ai-maestro server` line in either `daemon.log` or `daemon.log.1`.** The
daemon did not stand down. I inferred behaviour from a claim-state API instead of reading the
log that records what actually ran — the exact "decide on facts" failure, committed while
writing a card about verification.

### The VERIFIED timeline (facts only)

| when | what |
|---|---|
| Aug 5 **18:13** | `2.3.0` lands in cache |
| Aug 5 **21:02** | `2.4.1` lands in cache |
| Aug 5 21:02 → Aug 6 06:25 | **daemon completely silent — ZERO task lines in `daemon.log`** |
| Aug 6 **06:25** | reload generation stamped (9 h 23 m after 2.4.1 landed) |
| Aug 6 (all day) | owner's session still executing `2.3.0` skills |
| Aug 6 **16:35** | daemon runs `version-update` — a correct NO-OP (already at latest) |

`claimed_chores()` and the daemon's behaviour DISAGREE (it lists them as claimed; the daemon ran
one anyway). That disagreement is real and worth its own look, but it makes the daemon do MORE,
not less — it is not this bug.

### Where the evidence actually narrows to

**The reload WAS signalled at 06:25, and the session was STILL stale for the rest of the day.**
So the gap is in **CONSUMPTION, not signalling** — the opposite end from where I first pointed.
The 9 h 23 m of daemon silence spans an overnight window and is very likely just a sleeping
machine (correct, unavoidable behaviour), not a defect.

### OPEN QUESTIONS — do not answer these by inference

1. Was the machine asleep Aug 5 21:02 → Aug 6 06:25? (`pmset -g log` / `log show`.) If yes, the
   daemon gap is expected and the card's whole framing shifts to consumption.
2. Did the owner's session ever RECEIVE a `[janitor-reload]` after the 06:25 stamp — and if it
   did, why did it keep running 2.3.0? Check that session's transcript for the marker.
3. Why does `claimed_chores()` list chores the daemon runs anyway?

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

- [ ] today's non-convergence root-caused — **first answer WITHDRAWN as wrong** (see STATE). What
      IS established: the pin converged, the reload was signalled at 06:25, and the session stayed
      stale afterward ⇒ the gap is in CONSUMPTION, not signalling. Three open questions recorded
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
