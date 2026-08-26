---
trdd-id: A70YJLXN
title: The janitor plugin must update as soon as a new version is detected under EITHER daemon
column: todo
created: 2026-08-26T14:06:12+0200
updated: 2026-08-26T14:20:00+0200
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

- [ ] A decision among the three above, recorded here
- [ ] Whichever path is chosen, a measurement showing publish→installed latency under the SERVER
      that meets the directive — not a design argument that it should
- [ ] The janitor's own path re-verified unchanged (it already meets the directive; a change on
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
