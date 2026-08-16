---
trdd-id: JEEQCHFG
title: The runaway alarm's metric was misnamed and the fleet's false-positive tally is void
column: todo
created: 2026-08-16T18:40:00+0200
updated: 2026-08-16T18:40:00+0200
current-owner: ai-maestro-janitor
task-type: bugfix
supersedes: 8QSLYMGU
relevant-rules: []
implementation-commits: [80ce577a]
---

# The runaway alarm's metric was misnamed and the fleet's false-positive tally is void

Supersedes **TRDD-8QSLYMGU**, which is `column: complete` and therefore frozen. That card
is NOT edited: its ticked acceptance box is an accurate record of what was believed on
2026-08-16, and rewriting it would erase the evidence of how the error propagated. This
card carries the correction.

## What 8QSLYMGU got wrong

Its title and premise were *"the runaway alarm fires on a lifetime average"*. **`%cpu` is
not a lifetime average.** `man ps`: *"the CPU utilization of the process; this is a decaying
average over up to a minute of previous (real) time."*

Disproved three independent ways on 2026-08-16:

* `%cpu` != `time/etime` — pid 607 reported `99.0` while its lifetime ratio was
  638 s / 1,167,619 s = **0.055%**, off by a factor of ~1800.
* `%cpu` MATCHES consumption computed from `cpu_time` deltas over a known interval.
* `%cpu` DECAYS — the same pid went `100.2 -> 5.0` within minutes, which a 13-day
  denominator forbids. Another observer measured `59.4 -> 121.9` in 25 seconds.

The mechanism was invented, not measured, then repeated by six sessions until it arrived
here as a filed card whose acceptance box was ticked — and pinned by two passing tests, so
the false claim had a green guard.

## What is already FIXED (commit 80ce577a)

* `daemon_runaway.format_drift_line` now says `a ~1-minute decaying average; a live delta
  may differ on a bursty process`.
* Both pinning assertions in `tests/test_system_daemon_runaway.py` updated to the true text.
* The comment at the site records the measurement, so the next reader does not re-derive it.

## What 8QSLYMGU got RIGHT, and must not be undone

The `min_streak` consecutive-checks gate is **sound**. A claim that it "cannot corroborate
by construction, because it re-reads the same smoothed window seconds apart" was REFUTED
here: `dispatch.py:479` sets the detector interval to **600 s**. Ten minutes against a
~1-minute window means consecutive fires sample windows that do not overlap at all — they
are genuinely independent. Do not remove or weaken that gate on the strength of the
retracted mechanism.

## The open work

1. **The fleet's false-positive tally is EVIDENCE OF NOTHING and must be discarded, not
   adjusted.** Every entry was classified by comparing `ps %cpu` (a ~1-minute average)
   against `top -l 2` (a ~1-second delta). Those are not comparable, so 167% and 2.7% can
   both be true of the same bursty process. Re-measure from zero.
2. **Some dismissed alarms were probably CORRECT.** The discriminating test is whether the
   lifetime ratio and the reported `%cpu` AGREE: a burst makes them diverge, sustained load
   makes them converge. Observed on JumpConnect pid 3459 — 1348 s CPU over 1379 s wall,
   ~98% of a core for 23 minutes, both figures agreeing. That is a plausibly real runaway
   that was written off.
3. **UNANSWERED, and the real design question underneath all of this: is ~1 minute the
   right window for a runaway alarm at a 600 s cadence?** Nobody has scoped it. A one-minute
   average sampled every ten minutes can miss a nine-minute burn entirely, and can fire on a
   one-minute spike that nobody would call a runaway. Answer this before tuning thresholds.
4. **Independent of the metric question: is a pid re-validated before its alarm is emitted?**
   A peer observed an alarm naming a pid that no longer existed. That is a defect under any
   metric. NOT audited — the worker assigned to it stalled without filing.

## Acceptance

- [ ] The window question (3) is answered with a measurement, not an argument.
- [ ] Pid-existence at report time is audited and fixed if absent.
- [ ] A fresh runaway tally is built; the old one is not consulted.
- [ ] Any threshold change cites the window decision from (3).

## Notes

Origin of the correction: the ai-maestro session, which originated the false mechanism and
then came back to refute it against its own interest. Both directions of that exchange —
their retraction, and my refutation of their follow-up claim about the streak gate — were
settled by re-measuring rather than by argument.
