---
trdd-id: UQW5IOAE
title: An idle keep-warm session should be forced through handoff-and-clear to shrink its prefix
column: todo
created: 2026-08-02T14:19:42+0200
updated: 2026-08-26T11:20:00+0200
current-owner: claude-ai-maestro-janitor
task-type: feature
scope: project
severity: high
blocked-by: []
implementation-commits: [d2a5204, 67802e0, 5ecf47f2]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative)

### ⏵ 2026-08-26 — column corrected `testing` → `todo`. Nothing is being tested.

4 of 5 acceptance boxes are ticked. The 5th is the advisor-mandated SHADOW-MODE soak + staged
drill, and the card's own 2026-08-22 box says shadow mode **has no implementation** — so there
is no soak to be in the middle of, and `testing` was asserting an activity that cannot exist
yet. Confirmed no soak artifact anywhere under `reports/`.

**It is NOT blocked, and that distinction is the reason for `todo` rather than `blocked`.** The
disabled external-clear lever (`ec.enabled()` → early return) is only reason 1 of the three
INDEPENDENT reasons the card itself records; building shadow mode is ordinary unblocked work
that does not need the 3.4.0 publish, even though a live soak eventually will.

**⏵ 2026-08-26 — reason (3) is DONE; (1) and (2) are the OWNER's trade.** The audit channel is
built and tested (`5ecf47f2` — the watcher's verdict lines are kept, not sent to `/dev/null`).
No shadow data exists yet and none will until someone decides to run the disabled path in
dry-run per beat, which costs a fleet walk plus a watcher spawn WHILE THE FEATURE IS OFF —
precisely the cost `run_once`'s "ships inert" early-return exists to avoid. That is a trade,
not a patch, so it is not an agent's call. **NEXT ACTION on this card is a human decision, not
code.**

Everything the card already warns about stands unchanged — in particular **do NOT close this on
the 2026-08-14 triage row**; the advisor's DO-NOT-SHIP verdict landed the same day and rewrote
the boxes rather than ticking them.

**Not started. FABLE-ADVISOR VERDICT RECEIVED 2026-08-02 — it RE-SCOPES this card. Read the
verdict section below BEFORE the design notes further down, which were written on a premise that
turned out to be false.**

> **DO NOT close this card on the strength of the 2026-08-14 board triage.**
> `reports/trdd-triage/20260814_171024+0200-todo-planned.md` classifies UQW5IOAE
> **DONE-UNCLOSED** with the next action "move to `complete`; no code work left". **That is
> wrong now, and checked 2026-08-16 it was already going stale as it was written**: the triage
> is timestamped 17:10 on 2026-08-14, and the Fable-advisor verdict recorded below — **do NOT
> ship as designed** — landed the same day and caused three acceptance boxes to be REWRITTEN,
> not ticked. One of them now demands a shadow-mode soak plus a staged end-to-end drill, which
> is days of evidence, not a column move.
>
> Recorded here rather than left in the report because a report is EVIDENCE and a board move is
> a DECISION: acting on that row would have closed a card the advisor had just blocked, and the
> only thing standing between those two facts was noticing their timestamps. Citing the report
> by name here is also what tells `report-to-trdd-drift` the report was consumed — it clears on
> a TRDD naming the basename, so the honest way to silence it is to say what the report was
> right and wrong about.

### ✅ STEP 1 DONE — ROOT CAUSE FOUND AND FIXED (`d2a5204`). This card may not be needed.

**The diagnosis found a BUG, not a missing feature.** `_cadence_active_waiting` treated
`resume-directive.txt` as "actively waiting" on `is_file() and st_size > 0` with **no age
bound**, while its sibling signal one line above (the resume STAMP) has always been bounded to
30 min. The directive's ONLY consumer is `post-compact-resume.py` ("one-shot per compact"), and
the soft `/compact` is merely ENQUEUED — so a session that never ends its turn never consumes
it, and nothing else deletes it.

The measured session held FAST `*/5` for 2.9 h on a directive written **two days earlier**
(Jul 31). `last-resume.ts` was correctly 42 h stale; the transcript showed **195 of 249** recent
turns opening with `[janitor-heartbeat]` at a **285 s median** — our own cron, FAST tier, on a
session doing nothing. Fixed by bounding the CADENCE claim to the same 30 min window (the file
is still read as CONTENT). Mutation-verified.

**⚠️ TWO CONFIDENT WRONG ANSWERS PRECEDED THE RIGHT ONE — the reason this section exists:**
agentlensPro reported a **92 s** median gap. The advisor reasoned, correctly *from that figure*,
that no tier is that fast, so our cron could not be the driver. I recorded that as "the premise
was wrong" — in this very section. The transcript then showed 285 s ≈ `*/5`: the 92 s was
**REQUEST**-level and one turn makes ~3 requests. My original premise was right; the defect was
one level below it. **A metric's UNIT is part of the claim**; neither the tool nor the advisor
was wrong, and neither was checkable without going to the transcript.

### ✅ SHIPPED (`67802e0`) — and my "may be superseded" call above was WRONG

**OWNER REAFFIRMED the directive (2026-08-02, second statement), and the measurement in our own
tree proves them right.** I had written that `d2a5204` might supersede this card. It does not,
and `refresh_floor`'s own docstring is the disproof: a real compaction went **343,007 → 308,644
— only 10%**, because the base install *and the summary itself* reload every time. That floor is
*"a property of the install, not a number we get to choose."*

So `/compact` provably **cannot** go below ~308k here. An abandoned session costs ≥ floor × 0.1
per fire **forever**, and compacting again reclaims nothing. `/clear` is the ONLY lever that
drops the summary and gets under the floor — which is exactly what "reduce the context to a
minimum" means.

The two fixes **compose**: `d2a5204` cut the NUMBER of fires (a stale directive was pinning idle
sessions to FAST); this cuts the SIZE of each. A small context at FAST beats a fat one at SLOW.

**Shipped:** `cold_cache_compact.should_clear_when_long_idle` (pure) + its knobs/cooldown, and
`dispatch._phase_idle_clear_nudge`, wired immediately before the keep-going nudge so "shrink,
then continue" is the reading order. Gates: own knob (NOT coupled to the compact master), 6 h
idle, 350 k context (above the 308,644 floor), 2 h cooldown. **An UNKNOWN context or idle age is
a VETO** — `None` must never read as "small" or "idle forever" at the moment we know least.
Mutation-verified. Full suite 14,124.

### ✅ REACHABILITY MEASURED 2026-08-02 — the gate is NOT a filter that matches nothing

The old NEXT ACTION ("observe it fire once") was **unfalsifiable as written**: it waits on an
event without ever asking whether the event can occur. This session's recurring defect class is
*a filter that reads as correct and matches nothing*, so the gate was measured directly instead.

> **SUPERSEDED 2026-08-22 — the claim below ("never fired anywhere") is FALSE as of now, and
> the 350 k reasoning under it was already void** (the size term was dropped by owner directive
> 2026-08-04; see the advisor section). Re-measured today: **22 `idle-clear-fired.ts` stamps
> exist under `$HOME`**, spanning 2026-08-15 21:47 → 2026-08-22 00:56 — including a burst of 11
> projects inside 178 s on 2026-08-20 08:00. The nudge is live and reaching real sessions.
>
> **But NONE of those 22 counts toward the remaining acceptance box.** Every one predates
> `e607e95a` (2026-08-22 01:27:49), which is where `_phase_idle_clear_nudge` first VETOES on
> `awaiting_user` — before it, the flag was computed and thrown away, so the firing code was
> structurally incapable of distinguishing *abandoned* from *waiting on the human*. That is
> precisely the false-positive class the box exists to rule out, so the pre-fix record is
> evidence of REACH, not of SAFETY. **The soak clock starts at `e607e95a`, not at the first
> stamp.** Whether any of the 22 actually hit an awaiting-user session is not recoverable
> retrospectively — those transcripts have moved on — so do not try to audit them; count
> forward instead.

**It has never fired anywhere** — no `idle-clear-fired.ts` exists under `$HOME`. That alone says
nothing; the inputs decide. Measured across 45 project transcripts:

- **20 of 45 are ≥ 350 k.** Max seen **663 k**. The context threshold is comfortably reachable —
  it is not stranded above the population.
- **10 of 45 are ≥ 350 k AND idle ≥ 6 h**, so the *conjunction* is satisfiable too.

**But the 10 are all DEAD sessions** (idle 121 h – 1789 h). A dead session runs no heartbeat, so
the nudge can never fire in one — those rows prove the thresholds are well-placed, NOT that the
nudge will ever run. The live population sits at ≥ 350 k with idle **0 h**, i.e. working.

**So the honest reading: the defaults are sound and the target state (live + ≥ 350 k + idle 6 h)
is genuinely rare — which is what a nudge for abandoned-but-alive sessions SHOULD be.** No
change to 6 h / 350 k is justified by this data.

**Counter-check on this very session:** context **266 k** immediately after a compaction — i.e.
**below** the 350 k gate. So a session that has *already* compacted will not trip the nudge; only
one that grew past 350 k and went idle *without* compacting will. That is the intended shape (the
nudge exists precisely because `/compact` cannot go below its ~308 k floor), but it means the
nudge is **structurally unreachable for post-compact sessions** — worth knowing before anyone
"fixes" a future report of it never firing.

**NEXT ACTION (rewritten 2026-08-22):** none blocking, and nothing to build. The remaining box
is now a pure counting exercise with a defined start: re-run the stamp census
(`find "$HOME" -maxdepth 7 -name idle-clear-fired.ts`) and count only stamps **newer than
`e607e95a`'s commit time (2026-08-22 01:27:49 +0200)**. Zero false positives across those, plus
the staged end-to-end drill, ticks the box. Do NOT lower the thresholds to manufacture a firing,
and do NOT re-open the pre-fix 22 — they are dead evidence for this purpose.

### Verdict: NOT as external injection — a SELF-NUDGE, and probably not yet

- **Do not let the daemon (or any outside actor) type `/clear` into another session.**
  `clear_trigger.py` is built as a SELF-trigger: it resolves the pane from its OWN
  `$ITERM_SESSION_ID`, validates a handoff the MODEL authored that turn, and writes resume state
  synchronously because there is no PostClear hook. An external `/clear` has none of that —
  nobody authored a fresh handoff, and `/clear` with a stale or absent one is unrecoverable loss.
- **The safe owner is the session's OWN dispatch, and the safety then comes free.** A session
  parked on `ExitPlanMode`/`AskUserQuestion` or mid-long-tool cannot end its turn, so its cron
  never fires. A heartbeat-owned nudge therefore *structurally cannot* clear a blocked or busy
  session — the property the acceptance list below was trying to buy with tests.
  Mechanism: dispatch emits a marker → the model writes a FRESH handoff that turn → it invokes
  the existing skill, which runs `clear_trigger` with its own presence gate. **Never a
  `fleet_inject` keystroke path for `/clear`.**
- **`/compact` + the SLOW tier may already capture most of the win.** The idle burn is dominated
  by the ~308 k install floor (measured 343,007 → 308,644), so `/clear` reloads the same base
  prefix and beats `/compact` only by the summary + residue — a modest slice of ~507 k/fire.
  Cutting FIRES (`*/30` = 6× fewer) dwarfs cutting per-fire size.
- **The asymmetry is the whole answer:** being wrong that compact suffices costs measurable
  dollars, checkable in `token-meter.jsonl` after a week. Auto-`/clear` misfiring ONCE on a
  session with real in-flight state is unrecoverable.

**Owner directive reconciliation:** the directive said *force the agent to run
`/janitor-handoff-and-clear`*. The verdict does not refuse it — the agent still runs exactly that
skill. It changes only WHO pulls the trigger: the session's own heartbeat rather than keystrokes
typed in from outside. That preserves the intent and removes the unrecoverable failure mode.

**OWNER DIRECTIVE (2026-08-02, verbatim):** *"when that happens, you should force the agent to
run `/janitor-handoff-and-clear`, so to reduce the context to a minimum."*

**"When that happens" — the MEASURED trigger, not a hypothetical.** `agentlenspro
investigate_burn` on 2026-08-02 named `IDLE_FLEET_KEEPWARM` as a top culprit: ONE background
session (`~/Code/EMASOFT-ASSISTANT-MANAGER`) fired every **~92 s median for 2.9 h** with no user
present, re-reading its full prefix on every fire. Window total that day: **38.1M
input-equivalents, ~$203**, of which cache-READ was 324.3M tokens against only 4.5M cache-write.

## Why this is not the same as the cold-cache compact already shipped

TRDD-EUWIHP0G ships `/compact` on a COLD cache (the ≥1 h gap case) — the cache is already dead,
so the expensive rewrite is unavoidable and compaction makes every LATER resume cheap.

This is the opposite regime: the cache is **WARM and being kept warm**, so each fire is billed at
the cheap 0.1× cache-READ rate — but on a ~510 k prefix, 39 fires/hour, forever. Nothing is
broken, nothing looks wrong, and the session is doing no work. **Compaction may not be enough**:
it shrinks toward a learned floor that is still large. `/clear` reduces the prefix to
approximately nothing, which is the directive's "to a minimum".

That difference is the whole reason this is its own card and not a knob on EUWIHP0G.

## The danger, stated before the design

`/clear` is **irreversible** and the handoff is the ONLY survivor. Clearing a session that was
actually mid-something destroys real work with no undo. So the preconditions matter more than
the mechanism, and at least these must hold — this list is the question put to the advisor, not
a settled answer:

- the user is genuinely absent (`user_intent.user_is_present` / `injection_allowed`);
- the session is NOT blocked on a human (`fleet_scan.awaiting_user_decision` — an unanswered
  `ExitPlanMode`/`AskUserQuestion` looks identical to idle by every other signal; this is the
  exact trap TRDD-8IZ8COQ8 documented, where a guardian typed into an approval dialog);
- the session is NOT mid-long-tool (an unanswered `tool_use` also means a 20-min Bash is still
  running — the `ATOM-8IZ8-BROAD` lesson);
- the prefix is actually large enough for the trade to pay;
- the handoff was WRITTEN and VERIFIED before `/clear` is typed — `clear_trigger.py` already has
  `check_handoff_concise`; a `/clear` that outruns its handoff is pure data loss.

## Reuse, do not reinvent

`scripts/clear_trigger.py` (the two-phase `/clear` + bootstrap plan, and the handoff contract
check), `cold_cache_compact.py` (threshold/cooldown/floor-learning shape), `user_intent`,
`fleet_scan.awaiting_user_decision`, `fleet_recovery.gate` (cooldown + attempt accounting),
`terminal_trigger` (soft-vs-hard injection).

**Open question for the advisor, recorded so it is not lost:** which layer owns the trigger — the
DAEMON's fleet beat (it can see other projects' sessions, which is where the measured culprit
was) or the session's OWN heartbeat (it can see its own context size cheaply, and never types
into a pane it does not own)?

## Acceptance

- [x] Advisor verdict read and its objections either implemented or explicitly refused in
      writing. **Done 2026-08-14 — see `## Advisor verdict` below.** Verdict was DO NOT SHIP
      AS DESIGNED; every objection is answered there, and the boxes below were rewritten
      because of it rather than merely ticked.
- [x] **(REWRITTEN per advisor.)** Two layers, because one is provably insufficient:
      (a) PURE layer — mutation/neuter: disabling a veto must let a protected case through
      in a test; (b) GATHER layer — input-liveness: a fixture transcript ending on an
      unanswered `tool_use` must refuse END TO END. (b) is not optional. No mutation of a
      pure function can detect an input that never arrives, and TRDD-OO301H7D was exactly
      that bug — measured 2026-08-14, neutering the fix failed 1 of 54 tests, and the 53
      that still passed were the pure-layer ones.
- [x] A test proving a session blocked on `ExitPlanMode` is NEVER cleared.
      ~~**BLOCKED until TRDD-OO301H7D lands**~~ — **UNBLOCKED AND MET 2026-08-22.**

      This box told the next session exactly where to look, and it was right: *"re-verify
      against the in-model nudge path specifically, which is a different path."* It was, and
      it carried the same defect. `scripts/dispatch.py:2257` read
      `idle_s, _, _ = fleet_scan.transcript_activity(...)`, discarding `awaiting_user` — and
      `grep awaiting_user scripts/dispatch.py` returned NOTHING, so the flag was computed and
      never consulted anywhere in that file. A tail ending on an unanswered `tool_use` (which
      is what an open `ExitPlanMode` prompt IS) therefore read as "idle", and the nudge could
      propose clearing a conversation mid-interaction.

      `user_is_present` cannot cover this: presence is keyed on recent input, and a human
      reading a prompt produces none. That is why the flag exists and why discarding it was
      silent.

      Fixed in the same pass; the GATHER-layer test above went RED → GREEN on that one change,
      which is the proof both boxes were asserting.
- [x] A test proving `/clear` is not typed unless a verified handoff exists on disk.
      **Done 2026-08-16 — `tests/test_external_clear_never_clears_without_handoff.py`.** Two
      end-to-end assertions on the real `main()`, per this card's own advisor verdict that a pure
      mutation cannot catch a wiring defect: (a) a spy on `_fire` proves the handoff is on disk
      AND non-empty *at the moment the chain is spawned* — both events happening is not the same
      as the right one happening first, and an after-the-fact check could not tell them apart;
      (b) an `atomic_write` that raises proves the chain is never spawned at all. The invariant
      holds today by CONSTRUCTION (atomic_write raises; the write is a plain statement before
      `_fire`), which is precisely why it needed pinning: it is protected by the ABSENCE of a
      try/except, and wrapping a fallible write in one is the most natural "hardening" a future
      session would apply — silently turning a failed handoff into a destructive clear while
      every other test stayed green. Both tests are self-proving: (a) fails if `_fire` is never
      reached, (b) fails if `main()` never reaches the write.
- [ ] **(REPLACED per advisor — the old wording was unfalsifiable.)** Not "observed working
      once": that proves one TRUE POSITIVE, while the risk on an irreversible action is a
      FALSE positive, and this card's own data (10/45 candidates, all dead) says a live
      firing may never occur — so the old criterion waited on an event that may not happen,
      the very defect the STATE names. Instead: SHADOW MODE (log-only verdicts, every
      would-fire audited) for N days with zero false positives, PLUS one staged end-to-end
      drill on a sacrificial session proving handoff → `/clear` → bootstrap → old-transcript
      resume actually recovers.

      > **⛔ 2026-08-22 — SHADOW MODE HAS NO IMPLEMENTATION. The N-day clock cannot start,
      > and would not start by enabling the lever either.** Traced the whole chain today;
      > three INDEPENDENT reasons no verdict is ever recorded:
      >
      > 1. `cold_cache_clear_task.run_once()` returns at `if not ec.enabled(): return 0` —
      >    before the fleet scan, before any watcher spawn ("ships inert", deliberately).
      > 2. `external_handoff_clear.py` prints `DISABLED` and returns 0 **before** computing a
      >    verdict, unless `--dry-run` is passed. Nothing passes it.
      > 3. **The sharpest one:** the daemon spawns the watcher with
      >    `stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL`. So even AFTER the lever is
      >    enabled and the drill passes, every `VERDICT FIRE/HOLD … why=…` line the watcher
      >    prints goes to `/dev/null`. The audit trail this box asks for is discarded by
      >    design, in the enabled case too.
      >
      > So this is not a box waiting on time. It is waiting on a channel that does not exist,
      > and (3) means enabling the feature would not create it. Someone re-reading this in a
      > month would conclude "shadow mode has been running and found nothing", which is the
      > opposite of the truth — nothing has been running, and nothing is being found because
      > nothing is being recorded.
      >
      > **⏵ 2026-08-26 — REASON (3) IS FIXED. The channel now exists.** The daemon lane's
      > `subprocess.Popen(…, stdout=DEVNULL, stderr=DEVNULL)` in
      > `scripts/lib/cold_cache_clear_task.py` now appends to the component's own
      > `cold-cache-clear.log`, so every `VERDICT FIRE/HOLD … why=…`, `NO_SUMMARY`,
      > `HANDOFF_NOT_CONCISE` and `CLEAR_CHAIN_SPAWNED` line the watcher already printed is
      > kept instead of discarded. This was the half the box itself called "the cheap half and
      > unambiguously right", and the TRDD-VOWAUVE5 ordering lesson quoted below is exactly why
      > it went first: build the channel, THEN let the criterion depend on it.
      >
      > A file handle, not a pipe — the child is detached and nobody survives to drain a pipe, so
      > a full buffer would block it forever. `PYTHONUNBUFFERED=1` so a killed child still leaves
      > its lines. The SessionStart lane never had this hole (blocking, and it logs its own
      > verdict via `state.log_line`), so this was the single call site.
      >
      > Guarded by `test_the_watchers_verdict_lines_are_kept_not_discarded`, which is
      > neuter-proven: restoring `DEVNULL` fails exactly that test and no other (measured
      > 2026-08-26 — 1 failed, 8 passed).
      >
      > **REASONS (1) AND (2) ARE UNCHANGED, so no shadow data is being produced yet.**
      > `run_once()` still returns at `if not ec.enabled()` before the fleet scan, and
      > `external_handoff_clear.py` still prints `DISABLED` before computing a verdict unless
      > `--dry-run` is passed. The N-day clock therefore still cannot start — what changed is
      > that it now CAN be started by a decision, instead of being blocked on a channel that did
      > not exist.
      >
      > **NOT BUILT HERE, because it is a trade rather than a patch.** Shadow data requires
      > walking the fleet and spawning a watcher per candidate on every beat WHILE THE FEATURE
      > IS OFF, and `run_once`'s "ships inert" early-return exists precisely to avoid that
      > cost. Capturing the watcher's stdout into the janitor log is the cheap half and is
      > unambiguously right (an audit line the daemon already generates and throws away);
      > running the disabled path in dry-run to generate those lines is the half that costs
      > something and should be a decision, not an agent's initiative. The ordering lesson
      > from TRDD-VOWAUVE5 applies exactly: build the channel first, then let the criterion
      > depend on it — never the reverse.

## Advisor verdict — 2026-08-14 (Fable 5), and the answers

**VERDICT: do NOT tick the boxes and ship as designed.** Recorded in full because box 1
requires the objections answered in writing, not merely read.

### The STATE block above is STALE in three load-bearing places — all three VERIFIED

1. **The 350k size term was DROPPED**, owner directive 2026-08-04. Verified verbatim at
   `scripts/lib/cold_cache_compact.py:223-231`: *"SIZE IS NOT A TERM … a threshold high
   enough to never be met is a feature that does not exist."* Any reasoning in this card
   that relies on a size gate is void.
2. **The nudge INJECTS, it does not print**, same directive. Verified at
   `scripts/dispatch.py:2102-2112`: printing made the lever depend on an attentive reader
   *"on precisely the sessions that by definition have none. It never fired."*
3. **"Never let the daemon type `/clear`" (lines 101-124) is SUPERSEDED** by TRDD-PXP08ZQC
   plus the 2026-08-13 presence-removal directive. The daemon fleet-walks the external
   watcher today — verified at `scripts/daemon.py:1935`. Two cards asserted opposite safety
   doctrines over one lever; this one is the superseded side. **Do NOT carry lines 101-124
   forward as current doctrine.**

### The hole the review actually found — now fixed, separately

`external_handoff_clear.py:187` computed `awaiting_user` and discarded it, and
`should_clear_externally` had no parameter to receive it. So an 8-hour-parked plan approval
satisfied `long-idle`, met no veto, and would be cleared.

The bitter detail: **this card's own "Reuse, do not reinvent" list (line 169) already names
`fleet_scan.awaiting_user_decision`.** The signal was known, correct, free, and dropped by a
tuple unpack that named it `_await` — and the underscore convention announces "considered,
doesn't matter", which is exactly what stops a reviewer looking twice.

Filed and fixed as **TRDD-OO301H7D** (`fde1bf40`), not folded in here, because it is the
EXTERNAL daemon path while this card is the IN-MODEL self-nudge path.

### States the advisor says remain uncaught (open, not answered by OO301H7D)

- A background agent running **longer than 30 minutes** — the `active_waiting` stamp this
  card itself bounded to 30 min expires underneath it.
- **Unsubmitted draft text** in the input field. Only the injector's empty-field read-back
  catches it, and that is reliable on tmux only (`external_clear.py:1041-1046`).
- **Conversation-only knowledge exceeding the 8 KB handoff budget.** Inherent. Mitigated
  only if `--resume` on the old transcript is genuinely recoverable — *nobody has verified
  that*, and this card should not ship until someone does.

### Refused / deferred

Nothing refused. The advisor's recommendation (1) shipped as OO301H7D; (2), (3) and this
supersession record landed in the boxes above and this section. What remains open is
genuinely open, and is listed rather than quietly closed.

## Approval log

- 2026-08-14T18:10:00+0200 — Advisor verdict recorded; acceptance boxes 2 and 5 REWRITTEN
  (box 5's old form was unfalsifiable), box 3 marked blocked on TRDD-OO301H7D. Card stays
  `todo`: the verdict was DO NOT SHIP AS DESIGNED, and three STATE claims are now marked
  superseded. No scope change.
- 2026-08-12T15:39:16+0200 — RE-COLUMNED testing → todo by janitor-main-session. A WORK column
  asserts active work; nobody was working this (idle 10d). 0/5 acceptance, `blocked-by: []`, no
  external wait — just unstarted. No scope or acceptance changed.
