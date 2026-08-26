---
trdd-id: A70YJLXN
title: The janitor plugin must update as soon as a new version is detected under EITHER daemon
column: blocked
pre-block-column: todo
blocked-by: [peer-decision-absorbed-version-update-lane]
created: 2026-08-26T14:06:12+0200
updated: 2026-08-26T20:45:00+0200
current-owner: janitor-main-session
task-type: bugfix
project-id: ai-maestro-janitor
scope: project
severity: major
min-approval-requirement: none
labels: [version-update, absorbed-chores, ai-maestro, rollout]
npt: []
eht: []
implementation-commits: []
relevant-rules: []
---

# The two daemons update the plugin by DIFFERENT mechanisms, and only one is prompt

**USER directive, 2026-08-26:** *"No matter what daemon of the two is running, the ai-maestro
plugin must be updated as soon as a new version is detected on the marketplace."*

Today that holds for one of the two. Measured, not inferred.

> ⛔ **THE NEXT TWO SECTIONS ARE SUPERSEDED — read '2026-08-26 14:20 — TWO CORRECTIONS'
> below FIRST.** The mechanism table is WRONG (the server does run the update) and the
> latency table is WRONG (bad instrument). Kept unedited because the corrections only make
> sense against what they correct, and because the wrong reading was reached by quoting the
> right source about the adjacent chore — which is the reusable part.

## The two paths are not equivalent  ⛔ SUPERSEDED

| running actor | mechanism | trigger |
|---|---|---|
| **janitor daemon** (no server) | `daemon.task_version_update` runs `claude plugin update` itself, then sets `reload-needed.flag` and SIGTERMs the daemon so it re-spawns from the new cache | **detection** — GitHub ahead of local cache, gated on `CLAUDE_PLUGIN_OPTION_AUTO_UPDATE_ON_NEW_RELEASE` (default true) |
| **ai-maestro server** (absorbing) | keeps `autoUpdate: true` on every marketplace and lets **Claude Code** perform the upgrade on its own schedule | **Claude Code's cadence**, not detection |

The server's absorbed-duty tick **does not run `claude plugin update` at all**. Its own source
says so: *"the body stopped consuming the plugin lists when the user-plugins-update loop left
with its claim (TRDD-PE54D95Q AC6). Not reading the list at all is the strongest form of 'no
per-plugin loop' — there is nothing left to iterate."* What it does instead is keep marketplaces
`autoUpdate: true`, because *"Claude Code auto-updates a marketplace's plugins only when that
marketplace's `autoUpdate` is on"*.

Both are defensible designs. They are not the same guarantee, and the difference is invisible
from the janitor side: `version-update` is in `absorbed_chores`, so the janitor daemon correctly
stands down and its `version-update.last-run.ts` freezes (2026-07-25 here — CORRECT for an
absorbed chore, per `janitor-daemon-handover-unowned-chores`).

## Measured rollout latency on the passive path  ⛔ SUPERSEDED — bad instrument

Publish time from the GitHub release vs the local cache directory's mtime:

```
3.3.23  published 21:47 local  →  cached 22:41   ≈  54 min
3.3.24  published 22:35        →  cached 23:40   ≈  65 min
3.3.25  published 23:33        →  cached 02:31   ≈   3 h
3.3.26  published 02:23 (8-21) →  cached 14:45 (8-22)  ≈ 36 h
```

So it does deliver — but between ~1 h and ~36 h after publication. The directive asks for "as
soon as detected"; 36 h is not that. (Caveat on the method: a cache dir's mtime is an upper
bound on when that version arrived, not a creation stamp. The direction is unambiguous, the
exact figures are not — a cleaner measurement would read the install registry's own timestamps.)

**Current state is NOT stale:** marketplace latest `3.3.26` = cached `3.3.26`, verified today.
This card is about the guarantee, not about a live regression.

## ⛔ 2026-08-26 14:20 — TWO CORRECTIONS, both mine. The mechanism claim above is WRONG.

**1. The server DOES run the update.** `services/auto-update-service.ts:727-753` calls
`ChangePlugin(..., action: 'update', scope: 'user', ...)` on the janitor plugin. I quoted their
source accurately and about the WRONG CHORE: the "nothing left to iterate" comment is step 3
(`user-plugins-update`, whose loop left WITH its claim), while `version-update` is step 2 and is
alive. Two adjacent chores in one function. Refuted by ai-maestro-bf (their TRDD-FFHZM7XV), and
the claim/work pairing is therefore SATISFIED — option 2 (un-claim) is off the table.

**2. My 36 h figure was wrong, and my own stated caveat was the reason.** Cache-dir mtime is an
upper bound on arrival, not a creation stamp; the mtimes I tabulated were misattributed across
versions entirely. The real instrument is the install registry:

```
~/.claude/plugins/installed_plugins.json → the scope:"user" record
  version 3.3.26   lastUpdated 2026-08-21T00:31:07.623Z
  3.3.26 published                        2026-08-21T00:23:45Z
  ── LATENCY 7 min 22 s ──
```

**That instrument is positive-controlled, which matters because the peer believes no such
instrument exists.** Their `lastRunSummary` trail reports `updated` on 40 of 40 janitor rows
because `already-current` is reachable only when `ChangePlugin` FAILS — so `updated` means "the
command ran", not "a version moved". The install registry does NOT have that defect, and here is
the control: 50 of 75 user-scope records carry a `lastUpdated` ≥30 days old, and the janitor's own
is frozen at 08-21 while ~40 update attempts ran through 08-26. **If the field were rewritten on
every no-op it would be uniformly recent. It is not — it moves only on a real version change.**

## What actually survives, and it is still the directive

The guarantee concern stands, on different grounds than I gave: `ABSORBED_DUTY_INTERVAL_MS` is
**4 h**, polled every 15 min, and `absorbedDutyIsOverdue` decides purely on ELAPSED TIME. So the
worst case publish→attempt is ~4 h — cadence, not detection. The observed 7 m 22 s is one lucky
tick, not the guarantee.

**The peer proposed a third option, cheaper than either of mine, and I think it is right:** make
a pending `version-update-requested.flag` — the signal MY detector already raises, which they
already consume clear-before-run but never consult to DECIDE — make the lane overdue. One
disjunction in one pure function; the 15-min poller already exists; worst case 4 h → ≤15 min. No
porting, no second writer on `claude plugin update`, my lane stays down.

Superseding the options list above: **(1) port it — unnecessary. (2) un-claim — wrong, the work
exists. (3) relax the directive — still the owner's. (4) NEW: consume the detection flag in the
overdue predicate — the cheap correct fix, theirs to make.**

## ⏵ 2026-08-26 14:45 — NEITHER LANE INSTALLED 3.3.26. Proven from both sides.

The 7 m 22 s belongs to a third actor. ai-maestro-bf's absorbed ticks BRACKET the install rather
than containing it (`00:40:02+0200` and `04:41:39+0200`, install at `02:31:07+0200`), so their
lane did not do it. Mine could not have: `version-update.last-run.ts` reads 2026-07-25T21:01Z —
**26 days before the install** — because the chore is absorbed and my lane correctly stands down.

Two independent instruments, one conclusion: **PROVEN neither lane installed it. NOT PROVEN which
actor did.** Claude Code's own auto-update is the only other candidate either of us knows of
(`ai-maestro-plugins` carries `autoUpdate: true`), and that remains an INFERENCE — I looked for
positive evidence in `~/.claude/logs` for that window and there is none to be had.

### This reframes option 4, and the peer's reframing is better than my case for it

"4 h is too slow" is NOT the argument, because the usual path is ~7 minutes and belongs to
neither of us. **The argument is that the fast path fails SILENTLY and the backstop does not
notice.** TRDD-FXPV7L4D measured exactly that shape: 10 marketplaces unrefreshed for 11–155 days
while the lane printed "Refreshed every registered marketplace". When the harness stops, what
remains is a 4 h floor gated on elapsed time, never on detection — with my flag already crossing
the boundary unread.

So option 4 is **a detection-driven backstop under an unreliable fast path**, not a speed-up.

### The design is three actors, and none is sufficient alone

| actor | latency | fails when |
|---|---|---|
| harness auto-update | ~7 min observed (n=1) | **silently** — the FXPV7L4D class |
| absorbed lane + flag trigger (option 4) | ≤15 min | no armed janitor session on the host raises the flag |
| absorbed lane cadence | ≤4 h | never — the only unconditional floor |

The middle row's failure mode is mine: my detector raises `version-update-requested.flag` from a
per-SESSION heartbeat, so a host with no armed session never makes the lane overdue early and
falls back to the 4 h floor. Correct behaviour, worth knowing rather than discovering.

**The two silent failures are silent in DIFFERENT ways, and only one of them is ours to see**
(ai-maestro-bf's refinement, adopted). The harness stopping is invisible to both of us BY
CONSTRUCTION — FXPV7L4D found that class 11–155 days deep. But the flag's absence is
OBSERVABLE: "this host has no armed janitor session" is a state either side can read at any
time. So if option 4 is taken, the trigger degrading to the 4 h floor should be something the
lane SAYS OUT LOUD, not something found later — the difference between an unavoidable blind
spot and a chosen one. Neither of us has built this; it is a rider on option 4, not a
separate proposal.

**Nothing implemented on either side** — the change touches a shared chore contract, so it waits
on the owner.

## Why this matters right now



3.4.0 is the next publish (blocked on the owner's GH013 decision). Under the current server it
would reach the 16 sessions on Claude Code's cadence rather than on detection — which is the
shape of the complaint that opened this session's rotator work: *"it is failing all across the
16 claude instances"* while a fix was published.

## ⛔ What must NOT be done

**Do not add a janitor-side fallback that runs the update anyway when the chore is absorbed.**
TRDD-LU0C5KAR's binary coordination rule removed exactly that guard, and this repo's contract
says a running server that does not perform an absorbed chore is a SERVER bug, not a reason for
both actors to write. Two writers on `claude plugin update` is the janitor-issue-#7 pile-up.

**Do not hand-run `claude plugin update --scope user`** — user-scope writes belong to the single
writer (issue #7 / PRRD S2.1).

So the fix is one of:

1. **The server performs the update actively** for the absorbed `version-update` chore — the
   janitor's mechanism, ported, as `fleet-plugins-update` already was.
2. **The server un-claims `version-update`** and the janitor daemon runs its own lane again. The
   claim/work pairing is already the documented rule on their side: *"never re-add the name here
   without restoring the work, or vice versa."*
3. **The directive is relaxed** to accept Claude Code's cadence, in which case say so explicitly
   so nobody re-opens this.

(1) and (2) are the peer's call and are cross-project; (3) is the owner's.

## Acceptance

- [ ] A decision among the three above, recorded here.

      **NARROWED 2026-08-26 by the USER, in their own words this session** — not by my
      inference, which matters because I would otherwise have been choosing among three
      options one of which the owner had already excluded:

      > "is the janitor daemon (both this from the plugin and the one from ai-maestro when the
      > ai-maestro server is running) automatically updating the janitor plugin if a new version
      > is detected? **No matter what daemon of the two is running, the ai-maestro plugin must be
      > updated as soon a new version is detected on the marketplace.**"

      "As soon as detected", and explicitly indifferent to WHICH daemon is running. That is
      exactly option 3's negation: **relaxing the directive to accept Claude Code's cadence is
      OFF the table**, and so is any answer whose guarantee is a 4 h elapsed-time floor. It also
      names *detection* as the trigger, which is precisely what option 4 makes the predicate
      consult. Remaining live: **1, 2, or 4 — all three cross-project, all three the peer's
      call.** Nothing here is the owner's any more except a veto.
- [ ] Whichever path is chosen, a measurement showing publish→installed latency under the SERVER
      that meets the directive — not a design argument that it should
- [x] **RE-VERIFIED 2026-08-26 20:45, on the live host.** The janitor's own path is unchanged
      and behaving exactly as designed under absorption:
      - the flag mechanism is intact — `global_state._version_update_request_path()` /
        `request_version_update()` / `version_update_requested_present()` /
        `clear_version_update_request()`, canonical path
        `~/.claude/janitor-control/version-update-requested.flag` (control_dir, dual-read against
        the pre-control-dir location). **That absolute path is what option 4's predicate needs**,
        so it is written here rather than left as "the flag my detector raises".
      - `version-update` IS currently absorbed (server-liveness `absorbed_chores` lists it among
        nine), and our `version-update.last-run.ts` reads **2026-07-25** — frozen, which for an
        absorbed chore is the CORRECT observation and not a dead lane. Re-stated because this
        exact stamp has already misled one reader on this host.
      - no flag file present right now, i.e. nothing pending — consistent with the peer's
        clear-before-run consumption.
- [x] The asymmetry is documented where a reader will hit it: CLAUDE.md's working-rules section
      carries it inline (the "Known side effect … **Not a tamper signal, and on this host not
      transient either**" paragraph), naming the frozen `version-update.last-run.ts`, why an
      absorbed chore freezes it, and the `daemon.log` grep that names the refusing predicate. A
      reader hits it at the point they are told to upgrade locally, which is where the confusion
      actually starts — not in a reference page they would have to already suspect.
- [x] ~~The janitor's own path re-verified unchanged~~ (superseded by the box above; it already
      meets the directive; a change on
      the server side must not regress it)
- [ ] The asymmetry documented where a reader will hit it — a frozen `version-update.last-run.ts`
      must not be readable as either "healthy" or "broken" without saying which mechanism owns it

## Notes and lessons learned

Found by answering a USER question rather than from an alert: nothing on either side reports
this, because each actor is behaving correctly by its own contract.

[^1]: [id: LESSON-A70Y-1, status: active, keywords: is the plugin auto-updating,who actually performs the plugin update,the fix is published but sessions still run the old version,a chore is claimed but the work was deleted,absorbed chore with no lane behind it,two daemons and neither updates,frozen chore stamp that is correct,plugin update latency after publish, ocd: 2026-08-26, lmd: 2026-08-26]
    DO NOT read "chore X is in `absorbed_chores`" as "chore X is being performed", BECAUSE a
    claim and a lane are separate things and the claim SUPPRESSES the other actor's lane — so a
    chore claimed without work behind it is strictly worse than an unclaimed one, and the
    janitor-side stamp freezes in exactly the way a healthy absorption looks. DO read the
    absorbing side's tick body for the work itself, and confirm the OUTCOME (here: publish→cache
    latency) rather than the claim. Both projects already know this failure by name — the
    ai-maestro source calls it the TRDD-FXPV7L4D class and warns "never re-add the name here
    without restoring the work" — which is what made it findable.
