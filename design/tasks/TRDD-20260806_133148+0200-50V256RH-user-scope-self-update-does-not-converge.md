---
trdd-id: 50V256RH
title: The janitor does not converge itself to the latest version at user scope — sessions run stale code for a day while the fix sits cached
column: dev
created: 2026-08-06T13:31:48+0200
updated: 2026-08-06T19:20:00+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
scope: project
severity: high
relevant-rules: []
implementation-commits: []
---

# User-scope self-update does not converge (owner failure report 2026-08-06, item 5)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-06

**Root cause ESTABLISHED on the second attempt, from load markers.** `/reload-plugins` does not
re-point already-loaded SKILLS; only a NEW session does. My FIRST answer was wrong and is kept
below as a withdrawal — read it before trusting any claim-state API in this area.

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

### ✔ ROOT CAUSE — established from load markers, second attempt (the first is withdrawn above)

**`/reload-plugins` does not re-point already-loaded SKILLS in a live session.** Only a NEW
session picks up a newly cached plugin version.

Measured from `"Base directory for this skill: …"` lines — genuine load markers, not prose, not
an API's opinion:

| session | window (local) | skill loads | `/reload-plugins` runs |
|---|---|---|---|
| `be8c05d6` | Aug 5 → Aug 6 07:20 | **66 × 2.3.0**, ZERO 2.4.1 | 27 |
| `643908a6` | Aug 6 07:20 → 17:02 | **9 × 2.3.0**, ZERO 2.4.1 | 23 |
| `35e1e917` | Aug 6 17:03 → (post-`/clear`) | **2 × 2.4.1**, ZERO 2.3.0 | — |

Not one skill load resolved to 2.4.1 in either pre-clear session, though 2.4.1 had been cached
since Aug 5 21:02 and one of them ran `/reload-plugins` **23 times** — via a copy of
`janitor-reload-plugins` that was itself loaded from `2.3.0/skills/`. The fresh session after
`/clear` picked up 2.4.1 on its first skill load.

**So every link in the janitor's chain WORKED**: cache updated → reload generation stamped
(06:25) → `[janitor-reload]` markers delivered (23 and 18) → the reload command executed. The
harness simply does not re-point live skills, and nothing in that chain can.

**Why the session looked half-upgraded:** the auto-rolling stub always resolves the newest cached
version, so the CRON/detector path ran 2.4.1 while the SKILL path stayed 2.3.0 — two versions
live at once. That is exactly how the retired `USER_PRESENT` presence-cancel fired from a 2.3.0
`clear_trigger.py` (a skill-invoked script) while the heartbeat behaved like 2.4.1.

### THE CARD'S PREMISE IS INVERTED — and this changes other cards

The title says *"the janitor does not converge itself"*. It does: cache, pin and signalling all
converged. What does not converge is the **harness's loaded skill set**, and the ONLY lever that
moves it is a **new session** — i.e. `/clear` + bootstrap.

That makes TRDD-PXP08ZQC (external zero-turn clear) and TRDD-5C42VCUX (idle auto-clear) far more
than cost optimisations: **they are the only reliable version-convergence mechanism the janitor
has.** Weigh their gating decisions with that in mind.

### Remaining open questions (lower value now)

1. Was the machine asleep Aug 5 21:02 → Aug 6 06:25? Likely, and now moot: the 06:25 stamp did
   its job and the markers were delivered regardless.
2. Why does `claimed_chores()` list chores the daemon runs anyway? Real disagreement, unrelated to
   this bug (it makes the daemon do MORE, not less). Belongs to TRDD-6CRC9SQQ.
3. Is the live-skill staleness a harness LIMITATION or a bug worth filing upstream? Not
   determined — and filing is outward-facing, so it is the owner's call.

### NEXT ACTION (one step, runnable)

Answer OPEN QUESTION 2 — it is the cheapest and it decides the card's whole shape: grep the
owner's stale session transcript for a `[janitor-reload]` marker after `2026-08-06T06:25` local.

- **Marker present** ⇒ signalling worked; the defect is in CONSUMPTION (the session saw it and
  stayed on 2.3.0). Investigate what consuming it is supposed to DO and why it didn't.
- **Marker absent** ⇒ the 06:25 stamp never reached a session; investigate the stamp→marker path.

Then question 1 (`pmset -g log` for a sleep window) to confirm the daemon gap is benign.

### SUPERSEDED — do NOT carry forward

- The withdrawn root cause, and the fix it implied ("stamp from the OBSERVATION not the ACTION",
  with an ownership decision between the daemon's chore-coordination path and a per-session
  detector). That whole plan solved a problem the evidence says does not exist: the daemon did
  not stand down, and the reload WAS stamped. Do not resurrect it without new evidence.
- "the SERVER held the claim and did run both chores" as an explanation — `claimed_chores()` says
  claimed, the daemon ran it anyway, and which side performed the 16:35 no-op is not established.

### Verified (do not re-verify)

- `set_reload_flag` has exactly THREE call sites, all in `scripts/daemon.py` (grep, whole tree).
  TRUE — but it did NOT imply what I concluded from it.
- The timeline table above: cache dir mtimes, `reload_generation()`, and the daemon log's own
  task lines. Measurements, not inference.
- ZERO `yielding to active ai-maestro server` lines in `daemon.log` or `daemon.log.1`.

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

- [x] today's non-convergence root-caused — **`/reload-plugins` does not re-point already-loaded
      SKILLS in a live session**; only a NEW session does. Proven from `Base directory for this
      skill:` load markers: 66 and 9 loads of 2.3.0 with ZERO 2.4.1 across two sessions (one of
      which ran `/reload-plugins` 23 times), vs 2.4.1 immediately after `/clear`. The janitor's
      whole chain worked; the harness does not apply it. (First answer withdrawn — see STATE.)
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
