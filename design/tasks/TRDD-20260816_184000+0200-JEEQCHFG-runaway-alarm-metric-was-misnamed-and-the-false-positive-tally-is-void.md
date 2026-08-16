---
trdd-id: JEEQCHFG
title: The runaway alarm's metric was misnamed and the fleet's false-positive tally is void
column: todo
created: 2026-08-16T18:40:00+0200
updated: 2026-08-16T21:01:16+0200
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
2. **Some dismissed alarms were probably CORRECT.** Observed on JumpConnect pid 3459 —
   1348 s CPU over 1379 s wall, ~98% of a core for 23 minutes. Also on pid 26449, confirmed
   by three observers.

   **CORRECTED LATER THE SAME EVENING — do not use the test this item originally gave.** It
   said the discriminator is whether the lifetime ratio and the reported `%cpu` AGREE. That
   is unreliable, and my own measurement below breaks it: pid 26449 showed a cumulative of
   **100.0%** against an interval of **286%**. A cumulative ratio saturates near its
   historical mean and cannot exceed the core-count it has averaged, so on a long-lived
   process it "agrees" with any high reading by construction — a degenerate test that
   confirms whatever it is shown.

   **The only ground truth is INTERVAL DIFFERENCING**: read `ps -o time=` twice across a
   known wall-clock gap and divide. Everything else on offer — `%cpu`, `time/etime`,
   `top -l 2` — is an average over some window, and the entire failure of this investigation
   was comparing two such windows as though they measured the same thing.
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

## The retracted mechanism fails in BOTH directions (measured 2026-08-16 evening)

Everything argued earlier assumed the false mechanism OVER-reports ("a burst that already
ENDED still reads high"). It also UNDER-reports, and that direction is worse because it
produces SILENCE rather than noise.

Same pid (26449), one hour apart, three observers:

| when | cumulative (`time/etime`) | interval (differencing) | truth |
|---|---|---|---|
| earlier | 96.0% | **6.4%** | had STOPPED — cumulative OVER-reported |
| later | 99.3% | **191%** | ~1.9 cores live — cumulative UNDER-reported |
| my own check, 10 s window | **100.0%** | **286%** | ~2.9 cores live — under-reported ~3x |

**The structural reason** the CUMULATIVE column behaves that way: `time/etime` over the
process's whole life — here 11,511 s over 11,510 s — has a denominator so large after three
hours that no live excursion can move it. It is pinned near its historical mean and cannot
track a spike in either direction.

**⚠ BUT THAT IS NOT THIS DETECTOR'S METRIC.** `daemon_runaway.parse_ps_rows` reads
`ps -axo pid,ppid,rss,%cpu,comm` — it consults `%cpu`, never `time/etime`. So the cumulative
column above is context about the PROCESS, not a description of the alarm's input, and any
sentence of the form "a detector keyed on it reports X" does not apply here. That
conflation is retracted in full below.

What the table DOES establish, and this survives: the process was genuinely sustained at
the later readings, by interval differencing, which is the one method that is ground truth.

An alarm that cries wolf trains dismissal — which is what happened to this fleet today. An
alarm that stays QUIET during a real runaway trains nothing at all, because there is
nothing to observe. The second failure is undetectable from the outside, which is why it
survived unnoticed while the first was being argued about all evening.

### ⚠ RETRACTED — the section below is about `time/etime`, NOT about what the detector reads

**Everything in "Quantified: the number measures AGE" is FALSE OF `%cpu` and false of this
detector.** It is true arithmetic about the LIFETIME RATIO (`time/etime`), relabelled as
though it described `%cpu`. Kept, struck, because how it got here is the finding.

**Refuted in ONE ROW, no timing needed** — if `%cpu` were the lifetime ratio, the two must
be equal in the same row:

    pid 26449   reported %cpu = 10.3
                time/etime    = 12,084.44 s / 11,975 s = 100.9%
                DIFFERENCE    = 90.6 points

(A peer measured the same row shape independently at a 58.8-point gap, and dynamically:
`%cpu` swinging 90.8 → 122.2 → 95.5 while `time/etime` moved 100.32 → 100.34 → 100.49.
Nothing saturated swings 30 points in 20 s.)

**And the decisive fact I should have checked before writing a line of it:** this detector
parses `ps -axo pid,ppid,rss,%cpu,comm` (`daemon_runaway.parse_ps_rows`). It reads **`%cpu`**.
It has never read `time/etime`. So the saturation analysis was not merely mislabelled — it
was arithmetic about a number this codebase does not consult.

**WHAT INVERTS, and why this is not pedantic.** Under the retracted model a LOW reading
(`%cpu` 10.3) means "pinned near its historical mean, tells you nothing — discard it".
Under the truth it means **the process genuinely dropped to ~0.1 core during that minute**.
That is real signal, and the false model instructs the reader to throw it away. Threshold
logic sits directly on top of this reading.

**How it reached a durable card — the mechanism, which is the actual lesson.** This is the
SAME fabricated claim retracted earlier on this very card (see "What 8QSLYMGU got wrong"),
re-adopted hours later under a different name, by both parties, inside the correction to
it. The card contradicted itself and neither of us noticed: §"What 8QSLYMGU got wrong"
proves `%cpu` ≠ `time/etime` with pid 607 (99.0 reported vs 0.055% lifetime, ~1800x), and
then this section reasons as if they were the same quantity.

Two properties made it invisible:
* **Retracting a claim does not immunise you against re-adopting it renamed.** Only
  re-checking the premise does. The correction was written down, in the same document, and
  did not fire.
* **A wrong mechanism whose PRACTICAL ADVICE matches the right one meets no resistance
  anywhere downstream.** Both models say "use interval differencing", so every check
  passed, nothing contradicted it, and each reader added confidence instead of scrutiny.
  That is how the original lifetime-average error reached six sessions — and how this one
  reached a card whose subject IS that error.

### ~~Quantified: the number measures AGE, not load~~ (RETRACTED — see above; true of `time/etime`, false of `%cpu`)

From `cumulative_after = (C·T + r·t)/(T + t)`, with this process's own figures
(T = 11,510 s elapsed, C = 100.0%, r = 286% live). Verified by recomputation:

| burst at 286% | cumulative reads |
|---|---|
| 1 min | **100.96%** |
| 5 min | 104.72% |
| 10 min | 109.22% |
| 30 min | 125.15% |
| 60 min | 144.32% |

**+1.00 percentage point costs ~62 s of 286% load** — a sensitivity of ~0.97 pp/min that
decays as `1/elapsed`.

**The decisive row is not in the table.** The *same* 1-minute burst on a **5-minute-old**
process reads **131.0%**, against **100.96%** on this 3-hour-old one. Identical live
behaviour, a 30-point spread, determined by nothing but uptime. Past the first few minutes
the figure is not measuring load at all — **it is measuring age**. That is why no threshold
can work: there is no value that separates a hot young process from a hot old one, because
the metric does not distinguish them.

**Consequence for the fix — a test-design requirement, not a nice-to-have:** whatever
replaces the current gate MUST be validated against a process that is **live-hot but
historically QUIET**, not only against one that has cooled. The existing test corpus only
ever exercises the over-reporting direction, so it would pass a gate that is blind in the
direction that produces silence. A guard nobody has watched fail is not a guard.

## The RAM half — RAISED AND THEN REFUTED, same evening

**REFUTED. There is no memory finding. Do not carry this forward.**

It was raised because `ps` RSS read 2.07 GB and then 2.17 GB about an hour apart and `top`
printed a growth marker (`1798M+`). Both readings were single samples an hour apart, which
is a difference, not a trend.

The owner then took the actual series: **six samples over 75 s, net −117 MB**, oscillating
2220–2337 MB against a 6144 MB cap (~36%). That is a GC sawtooth on a healthy heap. The
growth marker was one point of an oscillation.

**The lesson is in HOW it was raised, and it is the sharper half.** Whoever raised it wrote
the correct caveat — *"two points, not a trend"* — and surfaced the claim to multiple
sessions anyway, as did I when I copied it onto this card. **A caveat is not a substitute
for the second measurement; it only makes an unfounded claim feel responsible.** The
honest options were to take the series, or to say nothing. Writing "I have not verified
this" and publishing it anyway is how an unfounded claim acquires a citation — which is
precisely the mechanism that produced the lifetime-average error this whole card exists to
correct.

(Attribution, since it was got wrong twice before anyone checked: pid 26449 is
`AgentlensPro/standalone/server.js` and TRDD-MFSUMOJ9 is **AgentlensPro's** card, not
llm-externalizer's.)
