---
trdd-id: LI7ENU2A
title: The cadence tiers' recovery-latency claim ignores cron jitter, and the two sources for it disagree
column: complete
created: 2026-08-02T07:50:55+0200
updated: 2026-08-02T19:25:00+0200
current-owner: claude-ai-maestro-janitor
task-type: docs
severity: LOW
scope: project
release-via: publish
parent-trdd: null
relevant-rules: []
implementation-commits: [e0299af3]
---

# The heartbeat cadence's latency claim is stated without jitter

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative)

**✅ COMPLETE 2026-08-02 19:25.** All three deliverables shipped, verification bullets met:

1. **Prerequisite fire-stamp** — `dispatch.main()` now stamps `fire epoch=<epoch>` into
   `.janitor/logs/heartbeat-fires.log` as its FIRST act after `init_state()`, before every
   early-returning phase (stop-mode included). Bounded by `log_line`'s structural rotation
   (S4); best-effort so telemetry can never kill a fire. Test:
   `test_main_stamps_fire_time_even_on_the_earliest_early_return` (proves the earliest
   return still stamps, and that it is per-fire, not once).
2. **`heartbeat_cadence.py` docstring** — the FAST-tier comment now states firing FREQUENCY
   unchanged, worst-case GAP = period + jitter, BOTH sources with their disagreement
   (CronCreate tool ≤10%/max-15min vs CC docs half-the-interval, checked 2026-08-02), and
   points measurement at fire times, never token-meter.
3. **Wikimem** (the post-slim home of the old CLAUDE.md cadence text) —
   `janitor-beat-tasks-and-limitations.md`: both claim sites corrected (tier table + the
   control-flow atom `ATOM-PHXC-VE71`), correction lesson `[^2]` (`ATOM-0AOD-B2GJ`) added
   via `memgrep add-lesson` per the protocol; validate + lint clean.

Repo-wide grep: no claim survives that a tier's recovery latency is exactly its period
(TRDD-0QQX9H0G is `published` — frozen, exempt per rule 12, and this card is its public
correction). No jitter NUMBER was fabricated: only the two documents' ranges are quoted,
with source + date; a measured figure waits for real `heartbeat-fires.log` data.

*(superseded original entry: "Not started. NPT #3 of TRDD-9K0O5YBQ's compatibility audit,
extracted 2026-08-02 (rule 9).")*

## The claim, and why it is optimistic

TRDD-0QQX9H0G justified the dynamic cadence partly on *"FAST `*/5` keeps recovery latency
IDENTICAL to pre-#83"*. That is true of the FIRING FREQUENCY and false of the WORST-CASE GAP,
because a scheduled task does not fire on the minute — it fires late by a documented jitter.

**The two sources for that jitter disagree, and neither can simply be adopted:**

| source | rule | worst-case gap at `*/5` | at `*/30` |
|---|---|---|---|
| CC docs page | up to 30 min, or up to HALF the interval for sub-hourly tasks | 7.5 min | 45 min* |
| `CronCreate` tool description | up to 10% of the period, max 15 min | 5.5 min | 33 min |

\* the docs' "up to 30 minutes" and "half the interval" clauses themselves conflict at `*/30`.

The audit's own instruction stands: **do not depend on either number.** The deliverable here is
not to pick one — it is to stop asserting a latency figure that ignores jitter entirely, and to
say which source was checked and when.

## Where the correction goes — NOT into TRDD-0QQX9H0G

`TRDD-0QQX9H0G` is `column: published`, and rule 12 freezes a terminal card's body. Do not edit
it. The correction belongs in the places a reader actually consults for current behaviour:

- `CLAUDE.md`'s heartbeat/cadence description (the living project map), and
- `scripts/lib/heartbeat_cadence.py`'s module docstring, beside the tier table it implements.

Both should state the gap as a RANGE with its source and date, not a single number.

## Worth measuring — but the data does NOT exist yet (corrected 2026-08-02, same day)

~~The honest fix is one observation: the heartbeat writes its own fire times … the janitor
already has the data — `token-meter.jsonl` carries a per-heartbeat record.~~

**That premise is WRONG, and I wrote it. `token-meter.jsonl` records turn END, not fire time.**
Its `ts` comes from the **Stop hook**, so it is offset from the fire by however long the turn ran —
minutes, on a working session. Attempted anyway, then caught by the shape of the result:

- **Inter-record gaps** (n=1,278): p50 **286 s** against a nominal 300, and **903 s** against 900.
  Useful as an end-to-end cadence observation — the typical spacing does track the armed tier — but
  it is *turn-to-turn* spacing, and a long gap cannot be told apart from a SKIPPED fire.
- **Lateness past the `*/5` wall-clock mark** (`ts mod 300`; valid at any tier since 300 divides
  900 and 1800, and a skip does not shift the phase) — n=1,292: p50 **121 s**, p90 266, p95 279,
  max 299. **Near-perfectly UNIFORM across [0,300).** That is not what jitter looks like; it is the
  signature of timestamps that are not phase-locked to the cron marks at all — exactly what
  turn-END times produce. The measurement measures turn duration, not jitter.

Reporting either as "measured jitter" would have manufactured a number more confident than both
documents and wrong. Do not resurrect them for that purpose.

**Nothing else records a fire time.** `dispatch.log` logs EVENTS, not every fire; the
`last-run-<detector>.ts` stamps hold only the most recent run; there is no `last-fire` stamp.

**So this card now has a prerequisite:** stamp the fire. The dispatcher already writes to
`.janitor/state/` on every fire, so the minimal change is one atomic append of the fire epoch
(bounded like every other append — see the S3/S4 boundedness invariants). Only then is the
distribution measurable, and only then should any number replace the two contradicting documents.

**Checked and dismissed while looking:** `dispatch.log` carries 1,644 lines reading
`detector 'report-to-trdd-drift' missing`, which looks like a live defect. It is not — every
occurrence is dated **2026-06-04 … 2026-06-12** under session `4eb7bf5d`, from before that
detector shipped. It is present today in BOTH the repo and the installed 2.3.0 cache (verified by
`ls`, same 12,623 bytes).

## Verification

- The stated latency in `CLAUDE.md` and `heartbeat_cadence.py` names a range, its source, and the
  date it was checked.
- No claim survives that says a tier's recovery latency is exactly its period.
- **If a number is quoted, it must come from FIRE timestamps.** Any figure derived from
  `token-meter.jsonl` is turn-END data and must be rejected in review — the uniform
  `ts mod 300` distribution above is the tell.
- The prerequisite fire-stamp lands first, bounded (no unbounded append).

## Notes and lessons learned
