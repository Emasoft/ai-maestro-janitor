---
trdd-id: 8QSLYMGU
title: The runaway alarm fires on a lifetime-average CPU sample with no persistence requirement, so a finished burst reads as an ongoing emergency
column: complete
created: 2026-08-16T04:29:41+0200
updated: 2026-08-16T05:34:00+0200
current-owner: unassigned
task-type: bugfix
project-id: ai-maestro-janitor
approval-tier: 0
severity: medium
scope: project
relevant-rules: []
npt: []
eht: []
external-refs: [TRDD-HK7IZ21Z, TRDD-D6RDPZIU]
implementation-commits: [540ee8ed]
---

# A burst that ended reads as "investigate before it exhausts the host"

## Measured twice in one night, same process, neither reproducing

`system-daemon-runaway` fired twice on 2026-08-16 against the same pid 74805 (an AgentlensPro
node server), and each time the headline figure failed to reproduce on an instantaneous sample:

| fire | alarm said | `top -l 2` (instantaneous) | host state at that moment |
|---|---|---|---|
| ~02:03 | `CPU 390% + disk 96% full` | **5.3%**, absent from the top 6 | 83 G free, swap 0, load falling 42 → 12 |
| ~04:28 | `CPU 161% + disk 96% full` | **28.3%** then **0.8%** | 81 G free, swap 0, load 5.96 |

Both times the alarm's own remedy line reads *"a process RAM/CPU runaway; investigate before it
exhausts the host"*. Both times there was no runaway and nothing was being exhausted — the machine
was measurably HEALTHIER at the second fire than at the first (load 42 → 6).

## Root cause — read from the code, not inferred from the numbers

`scripts/detectors/system-daemon-runaway.py:67` samples `ps -axo pid,ppid,rss,%cpu,comm`, and
`daemon_runaway.classify_runaway:121` flags on `row.pcpu > cpu_threshold_pct` (default 90.0).

**On macOS `ps %cpu` is a decaying average over the process's LIFETIME, not an instantaneous
reading.** A long-lived server that genuinely burned several cores for a stretch keeps a high
`%cpu` long after the burst ends. So the detector is not measuring wrongly — it is measuring a
*historical* quantity and presenting it in the present tense, with **no requirement that the
condition persist across fires**. One sample is enough to alarm.

That is the same defect class as TRDD-D6RDPZIU (closed today): a measurement surfaced without the
temporal context that makes it interpretable. There it was a finding with no age; here it is a
rate with no window.

## Why it matters more than a wrong number

The alarm is `actor: human` — it exists to pull a person's attention. This is the second time in
one night it has spent that attention on a process sitting near idle. Every non-reproducing alarm
makes the next real one cheaper to ignore, and this detector's whole purpose is the case where
something IS eating the host (TRDD-ZNN0UK5K: fseventsd at 39 GB / 97%, a genuine emergency).

Note what the detector is NOT wrong about: `fseventsd` has held ~75% CPU for 12+ days on this
host, all night, every sample. That is the sustained signal a persistence requirement would keep.

## The fix — decide the shape, do not just raise the threshold

1. **Require persistence.** Alarm only when the condition holds on N consecutive fires. The
   detector already keeps state (`system-daemon-runaway-seen.txt`), so the machinery exists.
   Raising the threshold instead would silence real slow burns without fixing the false ones.
2. **Say what the number IS.** Whatever survives, the text must name `%cpu` as a lifetime average
   (or switch to a genuine interval sample), so a reader who checks with `top` and sees 0.8% is
   not left concluding the janitor is broken — which is the reaction it produced tonight.
3. **Do NOT bundle the chronic disk line into the urgency.** `disk 96% full` has been true all
   night with **81–83 G free and zero swap**; pairing it with a CPU spike manufactures a compound
   emergency out of two non-events. Report it, do not escalate on it.

## ⏵ DESIGN SETTLED 2026-08-16 04:35 — read this before writing code

Traced the call path first. Cadence is **600 s** (`dispatch.py:479`), so a streak of 2 means the
condition held for ~10 minutes — the right order of magnitude for "sustained, not a burst".

**GATE CPU ONLY. Do NOT gate RSS — that would delay a real memory emergency.** `ps` RSS is an
instantaneous LEVEL (a process at 5 GB is at 5 GB right now); `%cpu` is the lifetime average this
card is about. `classify_runaway` already separates the two kinds, and the parent incident
(TRDD-ZNN0UK5K, fseventsd at 39 GB) was an **RSS** finding — gating it behind two fires would have
delayed the one alarm that mattered by ten minutes. This is the single most important line here.

**Keep `classify_runaway` PURE; put the streak in the DETECTOR, which already owns state.** The
codebase's split is pure-verdict / impure-caller and this must not break it:

```python
# daemon_runaway.py — PURE
def sustained_findings(findings, prior_streaks, min_streak=2) -> (list[Finding], dict[str, int])
```
- RSS findings pass through **ungated**.
- CPU findings increment `prior_streaks[key]`; reported only at `>= min_streak`.
- Keys absent this fire are **dropped** from the returned map — that is what makes an ended burst
  stop counting, and it is the behaviour the falsification test must pin.
- Key is `f"{pid}:{command}"`, never pid alone: pids are recycled.

**Detector wiring** (`system-daemon-runaway.py::main`, after `classify_runaway` at `:141`): read
the streak map from a new JSON state file, call the helper, **persist the new map even when the
gated list is empty** (otherwise the streak can never reach 2), then use the gated list for the
drift line. The existing `dedupe.emit_forget` on "nothing to report" still applies to the GATED
result.

**Text change** in `format_drift_line`: the CPU branch must say the metric is a lifetime average
and that it held across N fires. The RSS branch keeps its present wording — it is instantaneous
and its urgency is real.

## Acceptance

- [x] A single high-`%cpu` sample on an otherwise-idle process does NOT alarm; a sustained one does.
      `test_cpu_finding_is_silent_on_its_first_fire` + `..._alarms_once_the_streak_is_met`, and
      end-to-end across two REAL detector processes in `test_cpu_runaway_needs_two_fires_end_to_end`.
- [x] Falsified against the real shape: over threshold on fire 1, quiet on fire 2, over again on
      fire 3 — silent throughout, because fire 2 DROPS the key rather than carrying it
      (`test_a_burst_that_ended_is_dropped_and_must_start_over`, and the same three fires as real
      subprocesses in `test_cpu_burst_that_ends_never_alarms_end_to_end`). Independently falsified
      by running the new helper at `min_streak=1`, which reproduces the old behaviour exactly
      (1 reported vs 0) — so the gate, not something incidental, is what suppresses the burst.
- [x] The alarm text states the metric's window: `CPU 161% (a lifetime average, not a live sample;
      over the bar on 3 consecutive checks)`.
- [x] `fseventsd`-shaped input still alarms — `test_a_sustained_fseventsd_shaped_cpu_burn_still_alarms`
      pins five consecutive fires reporting `[0, 1, 1, 1, 1]` (silent once, then every fire).
- [x] An **RSS** finding still alarms on the FIRST fire, and contributes NO streak key at all —
      `test_rss_finding_alarms_on_the_first_fire_and_is_never_streaked` plus the real-subprocess
      `test_rss_runaway_alarms_on_the_very_first_fire_end_to_end`.
- [x] `uv run pytest` green; ruff + mypy clean.

Also delivered, from design item 3: the disk clause no longer escalates on a CPU finding (it is
reported, not called an amplifier), with the RSS branch keeping the wording where the amplification
claim is actually true — pinned in both directions by
`test_cpu_drift_line_reports_disk_pressure_without_escalating_on_it` and
`test_rss_drift_line_still_calls_disk_pressure_the_amplifier`.

## Notes and lessons learned

Found by verifying an alarm instead of acting on it, twice. The first verification is on
TRDD-D6RDPZIU (where it surfaced a different bug — undated findings); this card is what remained
once that one was fixed and the alarm STILL did not reproduce. Two independent defects were
wearing the same symptom, and fixing the first made the second visible.

**Autopsy — why the bug existed at all.** Nothing here was carelessly written: `classify_runaway`
was correct, tested, and pure; the threshold was reasonable; the fixture-driven tests all passed.
The defect lived entirely in the GAP between what `ps %cpu` measures and what a single sample of it
was taken to mean. No test could have caught it, because every test fed the detector one snapshot —
and one snapshot is exactly the input on which a lifetime average and a live sample are
indistinguishable. **The category is "a metric whose meaning depends on a window the code never
records"**, and the guardrail against it is procedural, not a test: when thresholding a metric, ask
what interval it covers before choosing whether one sample may trip it. Captured for reuse beyond
this repo as `ATOM-I2EH-TDH7` on the USER-scope page
`debugging-methodology-verify-before-concluding-instrumentation`.

**The trap that nearly got taken, recorded because it was tempting and wrong.** The obvious
symmetry — "the fix is a persistence gate, so gate both metrics" — would have been a REGRESSION,
not a tidier fix. RSS is an instantaneous level, and the incident this whole detector exists for
(TRDD-ZNN0UK5K, fseventsd at 39 GB) was an RSS finding: gating it would have delayed the one alarm
that mattered by a full 600 s cadence, to buy nothing. Consistency between two metrics is only a
virtue when they measure the same KIND of thing. `test_rss_finding_alarms_on_the_first_fire_and_is_never_streaked`
and its end-to-end sibling exist specifically so a later "cleanup" cannot quietly restore the
symmetry.
