---
trdd-id: 8QSLYMGU
title: The runaway alarm fires on a lifetime-average CPU sample with no persistence requirement, so a finished burst reads as an ongoing emergency
column: todo
created: 2026-08-16T04:29:41+0200
updated: 2026-08-16T04:29:41+0200
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
implementation-commits: []
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

## Acceptance

- [ ] A single high-`%cpu` sample on an otherwise-idle process does NOT alarm; a sustained one does.
- [ ] Falsified against the real shape: a fixture whose process is over threshold on fire 1 and
      under it on fire 2 stays silent, while one over threshold on every fire alarms.
- [ ] The alarm text states the metric's window, so an instantaneous cross-check that disagrees is
      explainable rather than evidence the detector is lying.
- [ ] `fseventsd`-shaped input (sustained, days long) still alarms — the case the detector exists
      for must not be lost to the fix.
- [ ] `uv run pytest` green; ruff + mypy clean.

## Notes and lessons learned

Found by verifying an alarm instead of acting on it, twice. The first verification is on
TRDD-D6RDPZIU (where it surfaced a different bug — undated findings); this card is what remained
once that one was fixed and the alarm STILL did not reproduce. Two independent defects were
wearing the same symptom, and fixing the first made the second visible.
