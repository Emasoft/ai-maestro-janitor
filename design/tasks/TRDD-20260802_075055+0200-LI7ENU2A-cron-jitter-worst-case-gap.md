---
trdd-id: LI7ENU2A
title: The cadence tiers' recovery-latency claim ignores cron jitter, and the two sources for it disagree
column: todo
created: 2026-08-02T07:50:55+0200
updated: 2026-08-02T07:50:55+0200
current-owner: claude-ai-maestro-janitor
task-type: docs
severity: LOW
scope: project
release-via: publish
parent-trdd: null
relevant-rules: []
implementation-commits: []
---

# The heartbeat cadence's latency claim is stated without jitter

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative)

**Not started.** NPT #3 of TRDD-9K0O5YBQ's compatibility audit, extracted 2026-08-02 (rule 9).

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

## Worth measuring, not just documenting

The honest fix is one observation: the heartbeat writes its own fire times. Compare consecutive
fire timestamps at a known armed tier (`.janitor/state/armed-cadence.cron` records it) and report
the OBSERVED distribution. A measured p50/p95 gap on this machine beats both documents, and the
janitor already has the data — `token-meter.jsonl` carries a per-heartbeat record.

## Verification

- The stated latency in `CLAUDE.md` and `heartbeat_cadence.py` names a range, its source, and the
  date it was checked.
- If measured: the observed inter-fire gaps at `*/5` and `*/15`, with n.
- No claim survives that says a tier's recovery latency is exactly its period.

## Notes and lessons learned
