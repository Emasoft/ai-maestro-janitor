---
trdd-id: D6RDPZIU
title: A resurfaced finding reads as a current measurement — the ledger stores the time and the render drops it
column: complete
created: 2026-08-16T02:04:59+0200
updated: 2026-08-16T02:08:03+0200
current-owner: janitor-main-session
task-type: bugfix
project-id: ai-maestro-janitor
approval-tier: 0
severity: medium
scope: project
relevant-rules: []
npt: []
eht: []
external-refs: [TRDD-KU3ERYFX, janitor#234]
implementation-commits: []
---

# A finding surfaced hours later still reads as "right now"

## The incident, measured tonight

A heartbeat fire at 02:03 surfaced:

```text
[system-daemon-runaway] node (pid 74805) CPU 390% + disk 96% full — likely the amplifier turning
FS churn into a balloon — a process RAM/CPU runaway; investigate before it exhausts the host.
```

Checked first-hand rather than acted on:

| claim | measured 02:03 |
|---|---|
| `node (pid 74805) CPU 390%` | `ps -axo %cpu` → **5.3%**; absent from `top -l 2`'s top 6 (so under 11.9%) |
| `disk 96% full` | true, and chronic — **83 G free**, swap **0.00 M used** |
| "investigate before it exhausts the host" | load average had *fallen* 42 → 12 over the evening |

And re-running `./scripts/detectors/system-daemon-runaway.py` right then produced **no output at
all** — the detector does not currently consider that process a runaway. So the line was not a
fresh measurement. It was an OLD finding being resurfaced, presented in the present tense.

The 390% was probably true when first recorded. That is exactly what makes this dangerous: the
alarm is not lying, it is *undated*, and an undated measurement is read as a current one.

## Root cause — the data is there, the surface drops it

`findings_ledger.record` stores a timestamp on every entry (`scripts/lib/findings_ledger.py:205`,
`"ts": int(time.time())`), and the unread cursor is built on it (`:349`). But `render_line`
(`:133-149`) reads only `sev`, `code`, `src`, `ref`, `msg`:

```python
return f"[findings] {sev} {code} ({src}): {msg} — ref {ref}"
```

Every surface goes through it — the heartbeat drift line (`:234`), the unread block (`:380`), and
`/janitor-findings` (`scripts/findings_cli.py:44`). So no reader anywhere can tell a finding
measured 8 seconds ago from one measured 8 hours ago.

## Why this matters more than its size

This is the same defect shape as the three found earlier tonight: **the information exists, the
surface that a human actually reads does not carry it.** Its specific cost is worse than clutter,
because the janitor's alarms compete for exactly one scarce resource — the human's willingness to
look. An alarm that sends someone to investigate a process sitting at 5% CPU spends that
willingness on nothing, and the next real alarm is read with less credit.

It also directly undercuts TRDD-KU3ERYFX (janitor#234), which made human-directed findings emit
once and be marked as human-only. Emitting once is right; emitting once *without saying when* means
the single emission a human sees may describe a condition that ended hours ago.

## The fix

Render the age of the MEASUREMENT on every finding line, always — never conditionally on it being
"old enough to matter". A line that shows an age only sometimes makes its absence ambiguous, which
is the same failure one level down (`ATOM-ZFUE-H8IZ`: silence cannot distinguish clean from
did-not-look).

- Append it, do not prepend: existing assertions and greps key on the `[findings] <sev> <code>`
  head, so a suffix is the compatible place.
- A missing or malformed `ts` renders as an explicit unknown, never as a silently omitted field —
  entries come off disk, where anything could have written them, and `render_line` is already
  documented to render defensively.
- Take `now` as an optional argument so the formatting is testable without freezing clocks.

## Acceptance

- [x] Every finding surface carries the age — all three go through `render_line`, so one change
      covers them. Confirmed on LIVE data, not only in tests: `scripts/findings_cli.py` now prints
      `… — ref - — 4m ago`.
- [x] A missing/malformed `ts` renders `age unknown`. Covers `{}`, `None`, a STRING timestamp, and
      `True` (a bool is an `int` in Python — excluded explicitly, or `ts: True` would render as
      1970). A backwards clock is the same case: a negative delta is unknown, never a measurement
      from the future.
- [x] Falsified — dropping the suffix reddens exactly the three new tests and nothing else.
      `test_the_drift_line_says_when_the_finding_was_measured` drives the real `record` path on
      purpose: the defect was that `record` STORED `ts` and the renderer never read it, so a test
      that built its own entry dict would have passed against it.
- [x] Existing assertions still pass — checked BEFORE choosing the suffix position: all three
      call sites assert by substring or prefix on the `[findings] <sev> <code>` head, none by
      equality. 164 tests across `test_findings_ledger`, `test_exfil_alarm_routing`,
      `test_quiet_heartbeat`, `test_dispatch_phases` pass.
- [x] ruff + mypy clean (485 source files).

## Notes and lessons learned

Found by verifying an alarm instead of acting on it. Worth recording that the FIRST measurement I
took was wrong too: `ps -eo %cpu` on macOS is a decaying lifetime average, so its 0.6% could not
have refuted a live 390% burst either — `top -l 2` (second sample) is the instantaneous reading.
Checking the harness before believing the measurement is what made the conclusion safe in both
directions.
