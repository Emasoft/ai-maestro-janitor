---
trdd-id: A70YJLXN
title: The janitor plugin must update as soon as a new version is detected under EITHER daemon
column: dev
created: 2026-08-26T14:06:12+0200
updated: 2026-09-05T17:38:28+0200
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

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-05

**2026-09-05 16:38 — the peer's option-4 commit `9725bebf` is in the running server's checkout on
this host, and is NOT on GitHub.** Measured read-only: `gh api repos/Emasoft/ai-maestro/commits/9725bebf`
→ 422 "No commit found"; no commit on ai-maestro `main` dated today; ai-maestro#156 is CLOSED
(stateReason COMPLETED, 09:25Z) by a comment from the hub-session Claude naming that SHA. In the
peer's local clone the commit exists (`fix(absorbed-duty): honour version-update-requested.flag on
the next POLL, not the next 4h tick`, 2026-09-05T09:52:10+02:00), unpushed, and it IS an ancestor of
`2fb4ef1c`, the checkout the running server reports in `~/.aimaestro/server-liveness.json`; the server
process started 5 s after that commit's timestamp. The server runs via `tsx` from the working tree and
the tree is dirty (8 files), so the loaded code was checked separately. **Correction (16:39):** a first
check reported `git diff 2fb4ef1c -- services/auto-update-service.ts` as empty — that run was vacuous
(zsh passed three paths as one argument). Re-measured with the single path: the file IS modified in
the working tree (55 diff lines, all in `ensureMarketplaceAutoUpdate` / marketplace-ops plumbing,
tagged TRDD-Y0XEEUXN — not the absorbed-duty poll), and its mtime is 16:35:06 today, i.e. AFTER the
11:16:27 server start, so the resident copy predates that edit. The `version-update-requested.flag`
check appears 3× in the committed file at `2fb4ef1c` and 3× in the working copy, 2× in the pre-fix
parent (`9725bebf^`). Bounded claim: the fix's flag check is in the committed file the server
started from and in every later version of it; whether the server has hot-reloaded since 11:16 was
not checked. A host installing the peer from GitHub does not have it. **Box 2 is now
measurable on this host at the next janitor release** (publish→installed latency; the peer's stated
figure is ≤15 min, one poll). Nothing here is the janitor's to fix; whether and when the commit is
pushed is the peer's/USER's decision. A first wording of this bullet (commit 455740bc) said "in
effect since 11:16" and "every other host is still on the 4 h floor" — the first was an inference
until the diff above, the second was never measured; both corrected here.

**Q1 — who RAISES `version-update-requested.flag`?** The janitor's own per-session
`version-update` detector, and nothing else in this repo. Writer:
`scripts/detectors/version-update.py:115` — `gs.request_version_update(f"{latest_installed}->{latest_published}")`,
inside the `auto_enabled` branch, gated on `CLAUDE_PLUGIN_OPTION_VERSION_UPDATE_ON_RELEASE_TRIGGER`
(default true). It calls `request_version_update()`, defined at
`scripts/lib/global_state.py:817-825`, which writes the flag file at the path returned by
`_version_update_request_path()` (`global_state.py:806-807`) — canonical
`~/.claude/janitor-control/version-update-requested.flag`. **The janitor's own detection of a
new marketplace version DOES raise the flag** — it is not only an external caller, though
`global_state.py:802` notes the flag design leaves room for "the ai-maestro server, not only
the daemon" to also raise it; no such second writer exists in this repo today (confirmed by
`grep -rn "request_version_update(" scripts/` — one call site only). Readers/clearers:
`version_update_requested_present()` (`global_state.py:810-814`) and
`clear_version_update_request()` (`global_state.py:827-831`), both consumed by the daemon.

**Q2 — what does the janitor still do while the server owns `version-update`?**
`scripts/daemon.py:3559-3569`: each loop resolves `yielded = _yielded_task_names(tasks,
harness_backend.server_runs_chores())` (per-chore claim via `harness_backend.claimed_chores()`,
`daemon.py:3046-3052`), then gates the fast-path consumer explicitly:
`if "version-update" not in yielded: _consume_version_update_request(tasks)`
(`daemon.py:3560-3569`). **While `"version-update"` IS in `yielded` (server claims it, which is
the case on this host per the re-verification below), the daemon does NOT call
`_consume_version_update_request` at all** — `task_version_update()` (`daemon.py:771-...`)
never runs, so the janitor never invokes `claude plugin update` for itself. The flag raised by
Q1's detector is left QUEUED, unconsumed (comment at `daemon.py:3558-3559`: "the requests stay
QUEUED, not consumed — so the moment the server drops, the takeover starts from the pending
queue"). So under the harness the janitor does **nothing** for its own update beyond raising
and holding that flag; the sole remaining janitor-side action is `task_integrity_repin`
(the C3 re-pin CLAUDE.md already documents) — it re-certifies the last-known-good version
pointer AFTER a version change has already landed by some other mechanism; it performs no
update itself.

**RIDER (the card's own ask):** the worst-case update delay under the current server-owned
chore is **not independently confirmable from this repo's own source** — `ABSORBED_DUTY_INTERVAL_MS`
and the 15-min poll live in the peer (`ai-maestro`) project, not here. What IS knowable from
this repo is the card's own Approval log (2026-09-05, RULED option 4): the peer's stated rule
is "server owns detection-triggered updates when up, flag honoured within one 15-min poll
(commit 9725bebf, ai-maestro#156); daemon owns them when liveness is stale >90 s" — i.e. the
**common case is ≤15 min** once the peer's fix lands, with a **4-hour unconditional cadence
floor** as the worst case if the flag path is somehow missed (per the card's own "What
actually survives" analysis, box `ABSORBED_DUTY_INTERVAL_MS` = 4h). Confirms, does not
correct, the card's existing 4-hour figure — this session found no janitor-repo evidence
narrowing or widening it.

**Boxes 2/3 remain open** (unchanged by this pass): box 2 needs a LIVE measurement of
publish→installed latency under the server with option 4 actually deployed peer-side (not yet
observable — nothing to measure until the peer ships commit 9725bebf's consuming logic and a
real release cycles through it); box 3 (the "SAID OUT LOUD" rider — the lane's degradation to
the 4h floor when no armed session raises the flag) is not yet implemented on the janitor side
per this session's grep of `scripts/` (no heartbeat/status line found announcing it).

**NEXT ACTION:** wait for/verify the peer's option-4 landing (ai-maestro#156, commit
9725bebf), then take a LIVE publish→installed latency measurement (box 2) using the install
registry method already validated in this card's body (`installed_plugins.json` `lastUpdated`
vs GitHub publish timestamp). Separately, implement the box-3 rider: a janitor status/heartbeat
line that says out loud when a host has no armed session raising the flag and is therefore
riding the 4h floor.

**USER directive, 2026-08-26:** *"No matter what daemon of the two is running, the ai-maestro
plugin must be updated as soon as a new version is detected on the marketplace."*

Today that holds for one of the two. Measured, not inferred.

**2026-09-05 17:27 — box-3 daemon-side counterpart implemented. ⛔ SUPERSEDED twice by
review before landing — see the 2026-09-05 17:50 entry below for what actually shipped.**
The 17:16 detector-side line only fires inside an armed session; a no-armed-session host
(daemon-only) had no statement at all. First cut keyed on flag-presence directly (wrong: the
peer's server-side consumer clears the flag within one poll, so "flag absent while yielded" is
the NORMAL steady state on a healthy armed host, not evidence nobody is watching). Second cut
keyed on a fleet armed-instance count (also a proxy: `gather_fleet` enumerates only
iTerm/tmux/ai-maestro panes, missing Terminal.app / headless `-p` / Claude Desktop sessions
that can still raise the flag). Kept unedited below because each correction only makes sense
against what it corrects.

**2026-09-05 17:50 — the literal signal that actually shipped.** Added
`global_state.py::version_update_last_raised()` reading a NEW never-consumed sibling stamp
`version-update-last-raised.ts` (written by `request_version_update()` alongside the flag) —
its age survives the flag's own clear-within-one-poll lifecycle, so it answers "was this
raised recently" when the flag itself cannot. `scripts/daemon.py::_floor_statement_due` (pure
predicate: due iff server owns the chore AND (`last_raised is None` OR stale past one 4 h
absorbed beat) AND ≥1 h since last logged) + `_maybe_log_version_update_floor_statement`
(loop-side wrapper, module-level `_VERSION_UPDATE_FLOOR_LAST_LOGGED` rate-limit clock, reads
`gs.version_update_last_raised()` itself). Called from the main loop's `else` branch of
`if "version-update" not in yielded:` — the original brief's location, runs every iteration
regardless of task budget/yield set. Logs to `daemon.log`: `chore-coordination: version-update
is server-owned on this host and no janitor session has raised version-update-requested.flag
in the last 4 h — a newer release lands on the peer's 4 h absorbed beat until a session
raises it (TRDD-A70YJLXN)`. Tests: `tests/test_daemon_version_update_floor_statement.py` — 5
cases on the pure predicate (never-raised/1h-ago/5h-ago/not-owned/rate-limited), 1 on the
stamp writer/reader round-trip, 2 on the real loop-side function with isolated global-state
(logs once across two back-to-back gate evaluations; silent when raised within the last 4 h).

**2026-09-05 18:05 — two more corrections, both from review, landing the final shape.**
(a) a plain "≥1 h since last logged" timer re-prints the SAME silence hourly forever on a
permanently server-owned host — replaced with memory keyed on the raise stamp itself
(`_floor_statement_due`'s `logged_exists`/`logged_value` params: due iff `last_raised`
differs from what was last logged for). (b) that memory was first a module variable —
erased by a daemon restart, and the corpus records a crash-loop mode where the daemon
restarts every heartbeat; a module-only memory would re-print on every restart in that mode.
Replaced with a PERSISTED sibling stamp `version-update-floor-logged-for.ts`
(`global_state.version_update_floor_logged_for` / `set_version_update_floor_logged_for`).
Also reordered `request_version_update()` to stamp `last-raised.ts` BEFORE the flag (a
reader can never observe the flag without the stamp), skipping the flag write entirely if
the stamp write fails.

**This satisfies the 2026-08-26 NEXT ACTION** ("implement the box-3 rider: a janitor
status/heartbeat line that says out loud when a host has no armed session raising the flag
and is therefore riding the 4h floor") **with the measurable substitute** "no session raised
the flag within one absorbed beat (4 h)" — chosen after two rejected predicates: flag-absent
(the peer's consumer `rmSync`s the flag within one poll, so absence is the NORMAL steady
state on a healthy armed host) and armed-instance-count (`fleet_scan.gather_fleet`
enumerates iTerm/tmux/ai-maestro-agent panes only, missing Terminal.app / headless `-p` /
Claude Desktop sessions that can still raise the flag). Code comment in
`_maybe_log_version_update_floor_statement` notes it can fire once during the ~90 s
server-death liveness handover — true at the time, harmless (not a state machine needing
undoing). Tests now 9: 6 on the pure predicate, 2 on the stamp round-trips (`last_raised`,
`floor_logged_for`) + 1 on the stamp-before-flag ordering, 2 on the loop-side function.

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

- [x] A decision among the three above, recorded here. **OPTION 4, 2026-09-05** — the peer's rule ('server owns detection-triggered updates when up, flag honoured within one 15-min poll, commit 9725bebf fixing ai-maestro#156; daemon owns them when liveness is stale >90 s') is exactly the card's option 4: absorbed lane + flag trigger, ≤15 min, 4 h cadence as the unconditional floor.

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
- [x] **RE-VERIFIED 2026-08-26 18:49, on the live host.** The janitor's own path is unchanged
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
- [x] The asymmetry documented where a reader will hit it — a frozen `version-update.last-run.ts`
      must not be readable as either "healthy" or "broken" without saying which mechanism owns it.
      **IMPLEMENTED 2026-09-05 17:16 — the "SAID OUT LOUD" rider (box 3), at RUNTIME not just in
      CLAUDE.md prose.** Added `version_update_lib.should_emit_floor_line()` (pure predicate:
      server owns the `version-update` chore AND a newer release is detected AND
      `version-update-requested.flag` is absent → the update is riding the 4 h unconditional
      cadence floor, not the <=15 min flag path). Wired into
      `scripts/detectors/version-update.py` Branch A2 (right after the existing flag-raise
      logic, so a flag just raised this pass correctly suppresses the line): emits
      `version-update: <installed> -> <published> detected; the ai-maestro server owns this
      chore and no flag is raised on this host, so the update rides the 4 h cadence floor (not
      the <=15 min flag path)` through the same `dedupe.emit_once` / `print(line)` drift channel
      its siblings use (quiet-filter + findings-ledger treat it identically). Tests:
      `tests/test_version_update_floor_line.py` —
      `test_floor_line_emitted_when_server_owned_and_newer_and_no_flag`,
      `test_floor_line_not_emitted_when_flag_present`,
      `test_floor_line_not_emitted_when_janitor_owns_the_chore`,
      `test_floor_line_not_emitted_when_no_newer_version` (4 passed). Gates: ruff, mypy, pyright
      all clean; `tests/test_version_update_daemon.py` (45 passed, unaffected).
      **17:21 addendum (coordinator ask) — 2 more tests drive the Branch A2 WIRING, not just
      the pure predicate.** Loaded `scripts/detectors/version-update.py` via
      `importlib.util.spec_from_file_location` (hyphenated filename, same pattern as
      `test_ci_status_detector.py`), isolated `CLAUDE_PROJECT_DIR`/`JANITOR_GLOBAL_STATE_DIR`/
      `JANITOR_CONTROL_DIR` into `tmp_path`, and monkeypatched ONLY the collaborators
      (`vu._SEMVER_RE`, `vu.list_installed_versions`, `vu.resolve_latest_published`,
      `harness_backend.server_runs_chores`, `harness_backend.claimed_chores`) — Branch A2's
      own code (the `line is None` guard, the `dedupe.emit_once` key, the printed text) runs
      for real. `test_main_prints_floor_line_when_server_owned_newer_and_no_flag` calls
      `mod.main()` and asserts the exact floor text appears exactly once;
      `test_main_suppresses_floor_line_when_flag_already_present` calls
      `mod.gs.request_version_update(...)` first (the real flag writer) and asserts `main()`
      then prints nothing about the floor. `tests/test_version_update_floor_line.py` now 6
      tests, all real, no mocking of the code under test. Re-ran: ruff/mypy/pyright clean;
      `pytest tests/test_version_update_floor_line.py tests/test_version_update_daemon.py` — 51
      passed.

      Scope note 2026-09-05: the detector line fires only inside an armed session with the
      release trigger opted out; the case where no janitor session has raised the flag within
      one absorbed beat (4 h) is covered by the daemon-side statement below (commit to be
      recorded by the coordinator).

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

## Approval log

- 2026-09-05T10:50:00+0200 — RULED option 4 by main-session on the peer's stated rule (ai-maestro hub session, 2026-09-05). Janitor work remaining: (1) the rider the card attached to option 4 — when no armed session exists to raise `version-update-requested.flag`, the lane's degradation to the 4 h floor must be SAID OUT LOUD by the janitor (a heartbeat/status line), not discovered later; (2) the asymmetry documented at the frozen `version-update.last-run.ts` (box 3); (3) a LIVE: measurement of publish→installed latency under the server (box 2). Column blocked -> dev.
