---
trdd-id: DLI76AUC
title: The heartbeat re-arm is a model turn, so the dynamic cadence can cost more than it saves
column: dev
created: 2026-07-14T21:34:32+0200
updated: 2026-07-14T23:46:37+0200
current-owner: janitor-session
task-type: refactor
scope: project
severity: high
labels: [heartbeat, cadence, token-economy, arm, skills]
relevant-rules: [1]
parent-trdd: 0QQX9H0G
---

# The heartbeat re-arm is a model turn

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-14

**NEXT ACTION:** Items 2, 3, 4 are DONE (commits `ea6a3b9`, `48523ca`, `a66c7a5`, `1959abc`).
The only open work is §Deferred item #1 (the demote hysteresis / re-arm cooldown) — the lever that
actually kills the churn — and it is **awaiting the USER's decision**. Do not start it unprompted.

**Scope approved by the USER (2026-07-14):** items **2, 3, 4** below. Item **1** (the demote
hysteresis) is DISCUSSED but NOT approved — do not change `heartbeat_cadence_demote_fires`.

**The janitor stays ALWAYS ARMED throughout.** Nothing here disarms anything. A renew is a
`CronDelete` immediately followed by a `CronCreate`; the cron never ceases to exist. What this
TRDD changes is how EXPENSIVE it is to rewrite the cron's period — not whether we are armed.

## The cost model (measured, not assumed)

From this project's own `.janitor/state/token-meter.jsonl`, weighted =
`output + input + cache_creation + 0.1×cache_read` (the code weights the write 1×; the `1.25`
this section first claimed was read out of a DOCSTRING, not the arithmetic — see `[^3]`):

| tool calls in the turn | weighted | per call |
|---|---|---|
| 1 | ~52,000 | 52k |
| 3 | 157,411 | 52k |
| 6 | 311,070 | 52k |
| 39 | 1,405,559 | 36k |

**Every tool round-trip re-reads the whole context at the 0.1× cache-read rate.** At this
session's ~520k context that is 520k × 0.1 = 52k per call — exactly what the table shows. So:

```
turn_cost ≈ tool_calls × context × 0.1
```

A quiet heartbeat fire is 1 tool call. **An arm is 6** (scope check, stub install, CronList,
CronDelete, CronCreate, record) — so **one arm ≈ six quiet fires**.

## The consequence: the cadence feature can be NET-NEGATIVE

`payback_time = arm_tool_calls / fires_saved_per_hour`

Demoting `*/5 → */15` saves 8 fires/hour. At 6 arm-calls: **6/8 = 45 minutes** to break even.

**The context size CANCELS OUT** — the arm cost and the fire saving are both 0.1× reads scaling
linearly with session size — so the payback threshold is a CONSTANT, not something to tune per
session. That is the load-bearing insight of this TRDD.

`heartbeat_cadence_demote_fires` defaults to **2**, which at `*/5` is **10 minutes**. The janitor
therefore commits a demotion 4.5× sooner than it can pay for it, and any activity inside the next
35 minutes re-promotes it. Observed live 2026-07-14: `*/15 → */5 → */15` in **25 minutes** — two
renews, ~620k weighted, saving nothing. There is also **no re-arm cooldown** anywhere.

## The work (USER-approved scope: 2, 3, 4)

- **#2 — collapse the arm from 6 tool calls to 4.** `arm_prepare.py` (scope check + atomic stub
  install + cadence resolve + print the PRIOR cron id) and `arm_record.py` (stamp
  `heartbeat-armed-at.ts` + `armed-cadence.cron` + store the NEW cron id). The skill then does:
  prepare → CronDelete(prior id) → CronCreate → record. **`CronList` disappears from the steady
  state**, because the prior id is now known from disk.

  **Crash-safety — which way a half-finished arm fails.** `arm_prepare` prints the stored id and
  then CLEARS it. So a turn that dies anywhere in the middle leaves NO stored id, and the next arm
  falls back to a full `CronList` sweep that deletes every janitor heartbeat before creating one.
  Clearing it LAST would instead leave a stale id pointing at a deleted cron while a newly-created
  one goes unrecorded — and the arm after that would create a SECOND live heartbeat, silently
  doubling the fire cost forever. This is the same "decide which way it fails" reasoning the skill
  already applies to `disarmed.flag`.

- **#3 — shrink the skills. DONE** (`ea6a3b9` arm, `48523ca` disarm). The arm went 12,528 → 5,715 B.
  The disarm went 7,154 → 6,635 B only — a deliberately modest cut, because the bulk of that file is
  three prohibitions and each one is a bug that already happened. Safety prose that must be read
  BEFORE acting cannot be demoted to a reference: a reference is read on demand, and a prohibition
  read on demand is a prohibition not read. The real find there was a CONTRADICTION — the disarm's
  checklist told the agent to write `disarmed.flag` directly, which step 3 of the same file forbids
  and which the guard exists to prevent.

  *(original scoping below)* `janitor-arm/SKILL.md` is 12,528 bytes ≈ 3,100 tokens, and it enters
  the transcript on EVERY invocation and then rides forward on every later turn. Its
  `## Known limitations` section (2,827 B) is a VERBATIM DUPLICATE of
  `references/janitor-architecture.md#known-limitations`, which the skill already links to. Cut it,
  keep the link. With the bash moved into scripts (#2) the Instructions section collapses too.
  Target ≈ 4 KB. Same treatment for `janitor-disarm` (7,154 B).

- **#4 — meter the arm turns. DONE (`a66c7a5`).** Root cause: the Stop hook returned early on
  `not usage.is_heartbeat`, so the meter logged heartbeat turns and NOTHING else — every
  interactive turn, a user-typed `/janitor-arm` included, was invisible. Note the TRDD's original
  premise was only half right: a RENEW-driven arm runs *inside* a heartbeat turn and was always
  metered; it is the user-typed arm that vanished. The fix logs every turn tagged
  `heartbeat: true|false`, which also repairs the report's rolling 5h/7d sums (they had been
  under-counting the user's own — i.e. the expensive — turns).

## Deferred — NOT approved, do not implement

- **#1 — the demote hysteresis.** Derive `demote_fires` from the payback (at `*/5`, 45 min ≈ 9
  fires, not 2), plus a hard re-arm cooldown. This is the lever that actually kills the churn, and
  #2 improves it for free (4 calls ⇒ 30-min payback; 3 ⇒ ~22 min). Discussed with the USER
  2026-07-14; awaiting a decision. **Do not touch `heartbeat_cadence_demote_fires` under this
  TRDD.**

## Out of scope — already built, verified 2026-07-14, do NOT rebuild

The cold-cache → `/compact` mechanism the USER asked about **exists and is enabled**:
`scripts/lib/cold_cache_compact.py`, wired at `dispatch.py:697-740` (after-idle) and
`on-session-start.py:151-192` (on-resume). Defaults `enabled=True`,
`min_idle_seconds=3600` (exactly the 60-min cache TTL), `min_context_tokens=270000`,
`cooldown_seconds=600`. It compacts BEFORE the next turn pays the rewrite of a dead cache — and
that rewrite is billed at **2×** (the main agent's 1-hour cache TTL), not the 1.25× of a 5-minute
one, so this mechanism is worth MORE than its own docs claimed. Shipped as TRDD-EUWIHP0G.

## Verification

1. An arm in the steady state issues exactly **4** tool calls (prepare, CronDelete, CronCreate,
   record) and NO `CronList`.
2. A first arm (no stored id) falls back to `CronList` and still works.
3. **Falsify the crash-safety:** kill the arm between `arm_prepare` and `arm_record`; the next arm
   must sweep via `CronList` and leave exactly ONE heartbeat. Assert no duplicate cron.
4. `arm_prepare` REFUSES a non-user-scope install (exit non-zero) — the step-0 guard must survive
   the refactor.
5. Both SKILL.md files are materially smaller, and every fact cut from them is still reachable
   through the reference they link.
6. The arm turn appears in `token-meter.jsonl` with its tool-call count.

## Notes and lessons learned

[^1]: [ocd:2026-07-14 lmd:2026-07-14] The dynamic-cadence feature (TRDD-0QQX9H0G) priced the
  FIRES it saves but never priced the TRANSITIONS it costs — and a transition is not a config
  write, it is a full Claude turn with six tool calls, because `dispatch.py` cannot call
  `CronCreate` and must ask the model to do it. Lesson: when an optimization's control loop runs
  through the MODEL, the control action is itself billed at model rates. Price the actuation, not
  just the steady state — an optimizer whose adjustments cost more than they save is a pessimizer.

[^2]: [ocd:2026-07-14 lmd:2026-07-14] I first "measured" the arm cost by matching the token meter's
  records to arm timestamps with a ±4-minute window, and reported that an arm costs 25× a quiet
  fire. It does not — the matched record had 39 tool calls and was the ticket-CLI WORK turn, not
  the arm. The label came from my own window, not from the data. Lesson: a join on a fuzzy key
  invents a relationship that the data never asserted. Verify the join before trusting the
  aggregate — and prefer a law you can see in the raw rows (here: cost ≈ tool_calls × 52k, visible
  directly in the table) over a summary statistic computed from a guess.

[^3]: [ocd:2026-07-14 lmd:2026-07-14] This TRDD's own cost table wrote the weighted formula as
  `output + 1.25×cache_creation + …`. The code weights `cache_creation` at **1.0×**; the `1.25`
  exists only in the surrounding DOCSTRINGS, and I asserted the arithmetic from a grep of the prose
  instead of reading the expression. That is the SECOND grep-as-proof error in one session (the
  first: a grep for `add_parser(` "proved" two ticket subcommands did not exist — they were
  registered in a loop). Compounding it, `1.25×` is the **5-minute-TTL** write price, while the main
  agent runs a **1-hour** TTL where a write costs **2×**. Both errors are now fixed in the source
  (`1959abc`). The cost LAW is untouched — it is `cache_read`-driven and 0.1× is right at either
  TTL. Lesson: **a grep of prose tells you what the author BELIEVED, never what the code DOES**; and
  a price is meaningless until you name the TIER it is charged at.

[^4]: [ocd:2026-07-14 lmd:2026-07-14] While verifying #4 the full suite failed once in
  `test_daemon.py` and once — a different run, a DIFFERENT test — in
  `test_marketplace_refresh_scoped.py`. I briefly concluded "this IS mine" off a single noisy run
  (a 12× slowdown looked damning). It was not: both pass 44/44 in isolation and repeatedly, the
  failing test moves between runs, and there is **no import path** from either module to the
  `token_meter`/`token_report` code I changed. The suite's own write-guard had already named the
  cause — the LIVE daemon mutating global state mid-run — and told me to `/janitor-global-pause`.
  Lesson: a failure that MOVES between runs is environmental; before blaming your diff, check
  whether the failing code can even REACH it. And when a test harness prints a diagnosis, read it
  before theorising. (The under-load flakiness of these subprocess/global-state tests is real and
  unfixed — it deserves its own TRDD, and it is not this one.)
