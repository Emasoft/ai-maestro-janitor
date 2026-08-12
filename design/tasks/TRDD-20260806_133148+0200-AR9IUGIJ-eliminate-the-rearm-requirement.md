---
trdd-id: AR9IUGIJ
title: Eliminate the re-arm requirement — no session should need /janitor-arm on every start, update, or tier change
column: backburner
created: 2026-08-06T13:31:48+0200
updated: 2026-08-12T09:40:00+0200
current-owner: claude-ai-maestro-janitor
task-type: spike
scope: project
severity: major
relevant-rules: []
implementation-commits: []
---

# Eliminate the re-arm requirement (owner failure report 2026-08-06, item 6)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-12

### CORRECTION 2026-08-12 — **option C is MOOT: the machinery it would tune was DELETED**

Everything below about C is written against code that no longer exists. Verified at HEAD:
`should_emit_renew`, `commit_tier`, `stable_count`, `raw_tier`, `committed_tier` and
`last_rearm_ts` return **zero hits** anywhere under `scripts/`. They were removed by
`af499ee3 feat(cadence)!: one arm per session — tier-driven renews deleted (USER directive,
TRDD-BRHJHWW0)`. The only surviving `[janitor-renew]` emitter is
`dispatch.py::_phase_heartbeat_renew` (`:1687`), which fires on the cron's **7-day expiry**,
not on a tier change. There is no oscillation left to dampen, so "raise `dwell_s`" is not a
smaller version of the task — it is a task about a deleted feature.

**What made this survive six days as a plausible NEXT ACTION:** `.janitor/state/cadence-state.json`
is still on disk (`{"raw_tier": "mid", "stable_count": 1, "committed_tier": "fast",
"last_rearm_ts": …}`, last written 2026-08-08). Nothing reads it and nothing writes it — grep for
`cadence-state` across `scripts/` and `skills/` returns nothing. An orphan state file is a
convincing witness for a feature that is gone; it is what a resuming agent finds first and it
agrees with the card. **Verify a cited symbol exists at HEAD before planning against it** — a
STATE block is a claim about the tree, and this one had gone stale without any edit to it.

So the spike's verdict collapses from **A + C** to **A alone**, and A is owner-gated. That is
why this card leaves `dev`: with C gone there is no step here anyone can pull, and `dev` was
asserting work that not only nobody was doing but nobody *could* do. Parked in `backburner`
(explicitly deferred), not `blocked` — nothing on the board blocks it; a human decision does.

---

**Spike DECIDED (2026-08-06). Verdict AS WRITTEN THEN: A + C — see the correction above; C is
now void. B was already shipped — and cannot do what the card asks of it.**

### THE LOAD-BEARING FINDING — B fixes RELIABILITY, not COST

Option B is **already live, end-to-end**, verified by running it 2026-08-06:

```
cron_dead  ->  action='rearm'  ->  command='/janitor-arm'
```

(`session_liveness.recovery_for_diagnosis` → `fleet_inject.action_to_command`, typed by the
daemon's `task_session_liveness` beat every 120 s, at every attempt count.)

**But B can never deliver acceptance box 2 as written ("re-armed with ZERO model-turn arm
cost").** Arming requires `CronCreate`, which is a **MODEL tool** — no daemon, hook or shell can
call it. This codebase already knows the shape: `clear_trigger.py`'s docstring records that "a
SessionStart hook is a SHELL script and CANNOT call CronCreate (a MODEL tool)", which is exactly
why the post-`/clear` bootstrap TYPES `/janitor-arm` instead of arming directly. B converts a
**missed** arm into a **performed** arm. The turn is paid either way.

So the card conflated two goals. Separated:
- **reliability** (a dark session self-heals) — **DONE**, shipped, verified above;
- **cost** (an arm stops costing ~6 quiet fires) — only A eliminates it; only C reduces it.

### The three options, costed

| | verdict | cost / evidence |
|---|---|---|
| **A** upstream durable crons | **PURSUE — the only true elimination** | `durable:true` is accepted-but-inert; the CronCreate tool's own docs say "Has no effect — durable persistence is not available… every scheduled job is session-only by platform design". Zero ongoing cost once landed. Timeline not ours. **Outward-facing → needs owner sign-off before filing.** |
| **B** external trigger | **ALREADY SHIPPED — close it out, do not build** | Verified live (above). Cost unchanged: still one model turn per arm, because CronCreate is model-only. |
| **C** cost-floor the arm | **PURSUE — the only cost lever we own** | Partly shipped: `should_emit_renew`'s dwell + `commit_tier`'s `demote_fires` are two independent hysteresis layers already. Remaining: tune `dwell_s`, and cut the arm's own round-trips. |

### Measured on THIS session today (first-hand, not modelled)

Two arms in one session: `*/5` at start, then a `*/15` **demotion** renew — which fired right
after a background agent finished, i.e. the exact flap TRDD-CI6ZTNB9 names. The arm executes as
**3 round-trips**, not 4, when `sweep=no` and the delete+create are batched into one response
(prepare → delete+create → record). That is already below the skill's documented 4-call contract.

### NEXT ACTION — ONE step, and it is entirely the owner's

**A:** file the durable-cron ask upstream (the CronCreate tool's own docs already concede
`durable:true` "has no effect… every scheduled job is session-only by platform design", so the
ask writes itself). **Not filed** — outward-facing publication is not something to do
unprompted. Nothing else on this card is runnable.

~~**C:** raise `should_emit_renew`'s `dwell_s`…~~ **VOID** — see the correction at the top of
this STATE block: `af499ee3` deleted the tier-driven cadence on a USER directive, so there is
no `dwell_s`, no `should_emit_renew`, and no flap to measure. Do not go looking for real flap
data; there is none to find, and `.janitor/state/cadence-state.json` will make it look like
there is.

### SUPERSEDED — do NOT carry forward

- Acceptance box 2's "ZERO model-turn arm cost in the common case" via option B. Structurally
  impossible: `CronCreate` is a model tool. Rewritten below.
- "option B may be mostly wiring + defaults, not new machinery" — it is not *mostly* wiring, it is
  **already wired**; the work there is zero.

## WHY

The heartbeat cron is session-only by platform design (`CronCreate durable:true` is
documented no-effect), so today the arm must re-run: at every SessionStart, after /clear,
on every `[janitor-renew]` tier change, and whenever the stub path moves. Each arm costs
~6 quiet fires' worth of tokens (TRDD-DLI76AUC measured it), the renew loop churns on
tier flapping (TRDD-CI6ZTNB9 — corroborated again today: one */5 promotion cycle right
after a background agent finished, then straight back to */15), and a missed re-arm means
a dark session. The auto-rolling stub already removed the per-UPDATE re-arm; the rest of
the requirement still stands and the owner wants it GONE.

## The spike (evaluate, pick, implement the winner)

- **A. Upstream durable crons**: file the ask on the Claude Code side (durable:true is
  accepted-but-inert today). Cleanest end state; timeline not ours.
- **B. External trigger**: the machine-global daemon (or the TRDD-PXP08ZQC watcher)
  detects an armed-project session whose cron died (restart//clear) and TYPES the
  heartbeat/resume via the ratified injection chain — the cron stops being the only wake
  source, so a lost cron self-heals without a model-side arm. Builds on
  fleet_scan's cron_dead diagnosis + fleet_inject (both exist).
- **C. Cost-floor the arm**: if A and B both fail, collapse the 4-call arm to fewer
  calls and stop re-arming on tier changes below a threshold (widen
  `should_emit_renew` hysteresis) so the requirement stays but costs ~nothing.

## Acceptance

- [x] one option chosen with measured/argued costs for all three — **A + C**; B verified
      already-shipped (see STATE)
- [x] a killed cron (restart or /clear) is re-armed without a MISSED arm — **already true**:
      `cron_dead → rearm → /janitor-arm`, typed by the daemon's 120 s beat, verified live
- [ ] ~~ZERO model-turn arm cost via B~~ — **structurally impossible, box withdrawn**:
      `CronCreate` is a MODEL tool, so no external process can arm. Replaced by:
      **the upstream durable-cron ask is filed + linked** (owner sign-off needed — outward-facing)
- [ ] renew churn from tier flapping measurably reduced (ties into TRDD-CI6ZTNB9) — needs a
      `dwell_s` value chosen against real flap data

## Pointers

- Arm cost + 4-call contract: the janitor-arm skill (TRDD-DLI76AUC).
- Tier machinery: `lib/heartbeat_cadence.py` (`should_emit_renew`, hysteresis).
- Recovery rungs that already type commands into panes: `lib/fleet_inject.py`,
  `lib/fleet_restart.py` (`cron_dead → rearm` exists TODAY as a daemon recovery —
  option B may be mostly wiring + defaults, not new machinery).
