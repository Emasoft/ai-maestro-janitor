---
trdd-id: WMQQYLSZ
title: Test fixture scripts pay a first-exec scan per file - invoke them as data instead
column: human_review
created: 2026-08-21T17:20:33+0200
updated: 2026-08-22T01:15:45+0200
current-owner: janitor-main-session
task-type: refactor
project-id: ai-maestro-janitor
scope: project
severity: minor
priority: normal
approval-tier: 0
labels: [tests, performance, flake, macos]
npt: []
eht: []
implementation-commits: [2cbb8a9b]
relevant-rules: []
---

# Test fixtures create a new executable per test, and pay for it on first exec

Derived from **TRDD-7NSRD8OV**, which measured the cost while chasing a different symptom.
That card owns the flake and its seam fix; this one owns removing the cost that feeds it.

## The measurement (2026-08-21, this host)

Dozens of tests do the same three steps: write a `.sh` into `tmp_path`, `chmod +x`, exec it.
On macOS the FIRST exec of a newly-created executable pays a one-time scan.

| shape | cost | n |
|---|---|---|
| fresh script, `chmod +x`, `./script` | **0.22–0.25 s** | 40/40 |
| the SAME 40 files, re-exec'd | 0.00–0.02 s | 40/40 |
| fresh script, `/bin/sh script` (data, trusted interpreter) | **0.00 s** | 12/12 |
| one outlier, fresh executable, machine saturated | **14.99 s** | 1 |

`tests/test_agentlens_probe.py` alone: **81.52 s saturated → 10.30 s quiet**, same code. Its 12
script-writing tests sat at 15.46 / 15.10 / 14.97 / 14.41 / 14.20 s under load and 0.22–0.26 s
quiet.

## Why it is worth removing rather than tolerating

The seam from TRDD-7NSRD8OV already absorbs the SYMPTOM — a 10× ceiling covers a 15 s scan — so
nothing is on fire. But it absorbs it by **waiting longer**, and the cost is one the tests
inflict on themselves per file. Passing the script as DATA to an already-trusted interpreter
removes it outright and is **load-immune**, because there is no new executable to scan.

Two payoffs, in order of importance:

1. **Headroom, not just speed.** Every fixture script that stops racing a scan is one fewer way
   for an unrelated timeout to expire under load and surface as the empty-stdout signature that
   cost this card four misdiagnoses.
2. **Wall-clock.** The probe file alone drops ~8 s quiet, and considerably more under the
   parallel gate where the scans contend.

## Scope

Test fixtures ONLY. **No production call site changes** — production genuinely execs real
binaries, and rewriting how the janitor invokes them would trade a measured guarantee for test
convenience. If a test's SUBJECT is the executable bit or the exec path itself, it keeps
`chmod +x` and says so in a comment.

## Acceptance

**RE-SCOPED AND CLOSED 2026-08-22 — the sweep this card proposed is NOT owed.** The card assumed
the cost was spread across ~28 files. Measured, it is concentrated in ONE, and that one is done.

- [x] The class is enumerated — and the enumeration KILLED the sweep. 27 files `chmod` a fixture
      executable, but **16 cannot convert at all**: their fixtures are PATH-resolved fake binaries
      (`bin/claude`, `bin/lean-ctx`, `aimaestro-agent.sh`) that production code invokes BY NAME,
      so the exec bit is load-bearing. Converting them is not a refactor, it is a break.
- [x] Converted where it pays: `tests/test_agentlens_probe.py` only (13 fixture execs, the
      densest site by 6x). `_write_script` returns `/bin/sh <path>` and no longer chmods.
      Callers unchanged — it always returned a command STRING and `shlex.split` absorbs the extra
      token.
- [x] Before/after on the same quiet machine: **10.30s → 2.80s, 37 passed.** A 3.7x drop from one
      line.
- [x] The other 11 candidates are deliberately NOT converted. Measured: 3 of them (4 fixture
      sites) run 208 tests in 5.18s, so the whole remaining population is worth **under 1 second**
      spread across a parallel suite. Eleven file edits for that is churn, not laziness.
- [x] Gates: full suite green at the time of the change (15750 passed / 0 failed), ruff + mypy
      clean.

**The general lesson, which outlives this card:** the fix belongs where the cost CONCENTRATES,
and you cannot know where that is by counting files. Counting call sites per file is what turned
a 28-file sweep into a one-line change — and the same count is what proved 16 of them were never
convertible in the first place.

## Notes

**Do not extrapolate a rate from an unrepresentative window.** While finding this I twice drew
a wrong conclusion from a partial measurement: once projecting "2.6 hours" for the suite from
its first 291 marks (the probe files sort early and are the slowest), and once from a serial
`pytest` when the gate runs `-n auto` and finishes in 240 s. Both would have sent the next
session hunting a regression that did not exist.

**The 14.99 s figure is ONE sample** and did not reproduce across 40. It is evidence the tail is
heavy, not the typical cost. The 0.22–0.25 s band is the reliable number.

**The attribution is indirect.** The exec-vs-data discriminator is strong, but no named scanner
was identified, so "macOS scans a new executable on first exec" is the best-fit explanation
rather than a proven one; dyld/codesign caching was not ruled out. The FIX does not depend on
which it is — passing the script as data avoids the cost either way — but a future reader
should not cite the cause as settled.

## Approval log
