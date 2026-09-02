---
trdd-id: O7UCNNN2
title: A heartbeat fire is a substantive transcript turn, so an ARMED session is never idle to the external-clear lane — the daemon can only ever clear sessions the janitor does not run in
column: dev
created: 2026-09-02T02:42:18+0200
updated: 2026-09-02T02:42:18+0200
current-owner: janitor-main-session
task-type: bugfix
scope: project
project-id: ai-maestro-janitor
severity: high
min-approval-requirement: none
blocked-by: []
npt: []
eht: []
relevant-rules: []
external-refs: [TRDD-XCJFCJUX, TRDD-NDAARSXT, TRDD-PXP08ZQC, TRDD-1QJIZFFW, TRDD-2F3I2P18, TRDD-8DR0X08A]
implementation-commits: []
---

# The clear lane's "idle" can never be reached by a session whose heartbeat is armed

## Measured 2026-09-02 (not inferred)

- After the 3.4.4 restage (daemon pid 41920, 02:28:33) the cold-cache-clear beat ran every
  ~5 min ("done in 1s") and logged NO `evaluating` line — none since 00:47. A probe with the
  installed 3.4.4 libs, run the way the task runs: `enabled() = True`, 5 fleet instances,
  every one `active=True`, all with a state dir, none in cooldown. So the beat walks the
  fleet and `continue`s past every instance, silently.
- `fleet_scan.ACTIVE_FRESH_S = 5 * 60`. `Instance.active` is
  `transcript_activity(root).age < ACTIVE_FRESH_S`, and `transcript_activity` returns the
  age of the newest SUBSTANTIVE transcript line — "substantive" excludes ONLY
  `queue-operation` bookkeeping (TRDD-8DR0X08A). A heartbeat cron fire appends a user
  prompt, an assistant turn and its tool records: ALL substantive.
- The heartbeat cadence is `*/5` (fires ~285 s apart here). So an armed session's
  substantive age cycles 0→~285 s and is `< 300` at EVERY daemon beat: `active=True` forever.
- The watcher gate has the same input: `external_handoff_clear._decide` feeds
  `idle_s = fleet_scan.transcript_activity(...)` against `clear_min_idle_seconds()`, default
  `DEFAULT_CLEAR_MIN_IDLE_SECONDS = 3600`. An armed session's idle can never exceed ~300 s, so
  the 1-hour floor is unreachable by construction.

**Consequence.** The daemon-driven external clear (the abandoned-session lane of
TRDD-PXP08ZQC) cannot fire on any session where the janitor heartbeat is armed — which is
every session on this machine. The two earlier reasons it never fired (watcher not staged,
NDAARSXT; options invisible to launchd, XCJFCJUX) hid this third one. The only sessions it
could ever clear are un-armed ones, or armed ones whose heartbeat is stalled — the latter
being exactly the sessions whose transcript the clear-first ordering must not disturb.

## Why the fix must NOT touch `transcript_activity`

`transcript_activity` is also the fleet guardian's liveness signal (`session_liveness`,
the frozen/wedged diagnosis and its recovery injection). Making heartbeat turns invisible
THERE would make every healthy idle session look stale and re-open the re-inject loop
TRDD-8DR0X08A closed. The clear lane needs a DIFFERENT measure, not a changed one.

## The discriminator (measured on this session's transcript)

A cron-fired prompt is a `type: user` record whose top level carries `scheduledFireId`
and `scheduledTaskId` (and `promptSource`, `userType: external`); it is preceded by a
`queue-operation enqueue` record with the same content. A human/agent-typed prompt carries
none of the `scheduled*` keys. Tool results arrive as `type: user` records whose
`message.content[0].type == "tool_result"` — those belong to the CURRENT turn, they are
not prompts.

## Fix

1. `fleet_scan.human_activity_age(root, now) -> int | None` (new, pure over the same tail
   read): walk the tail backwards, grouping records into turns delimited by PROMPT records
   (user records that are not tool results); a turn whose prompt carries `scheduledFireId`
   is heartbeat activity and is skipped whole; the first turn whose prompt is NOT scheduled
   yields the age of its newest record. Tail exhausted inside a scheduled turn → the age
   of the OLDEST scheduled prompt seen (conservative: "at least this idle"). No prompt at
   all → fall back to `transcript_activity`'s age (unknown shape ⇒ count as activity).
   Expose it on `Instance` as `human_active` / `human_age_s` WITHOUT changing `active`.
2. `cold_cache_clear_task.run_once`: skip on `inst.human_active`, not `inst.active`; and
   when a beat evaluates nothing, log ONE summary line with the skip counts
   (`active=N no-state-dir=N cooldown=N self=N`) plus `record_outcome("declined:no-candidate")`
   — a silent `return 0` at the end of the loop is the NDAARSXT shape again.
3. `external_handoff_clear._decide`: `idle_s` for the clear gate = `human_activity_age`
   (the `min_idle_s` comparison), leaving `trailing_enqueues`/`awaiting_user` as they are.
4. Tests: a synthetic transcript tail with a human turn followed by three heartbeat turns ⇒
   `human_activity_age` = age of the human turn, `transcript_activity` age unchanged
   (both asserted side by side so the separation is pinned); tail all-heartbeat ⇒ oldest
   scheduled prompt's age; tool-result records never count as prompts; run_once skips on
   `human_active` and logs the summary line when nothing qualifies.

## Acceptance

- [ ] `human_activity_age` exists, pure, tested against the record shapes above; liveness
      diagnosis (`transcript_activity`) byte-for-byte unchanged in behaviour
- [ ] the clear lane (task pre-filter + watcher gate) uses it; a beat that evaluates nothing
      logs why and stamps an outcome
- [ ] `ruff check scripts tests` + `mypy scripts/` + touched tests green
- [ ] after publish + restage: `cold-cache-clear.log` shows an `evaluating <root>` line for
      an armed session that was idle in HUMAN terms (this closes XCJFCJUX box 4 too)

## Notes and lessons learned

- Three independent reasons kept one lane dark for a month, each found only after the
  previous one was fixed. When a feature has "never fired in production", assume the
  reasons stack: fix one, then MEASURE again before declaring the lane alive.
