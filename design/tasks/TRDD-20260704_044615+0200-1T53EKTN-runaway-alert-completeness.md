---
trdd-id: 1T53EKTN
title: S6+S7 — memory-guard alert on unkillable system runaways + APFS-aware dual disk metric
column: todo
created: 2026-07-04T04:46:15+0200
updated: 2026-07-04T04:46:15+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 4
severity: MEDIUM
effort: M
task-type: feature
parent-trdd: TRDD-ZNN0UK5K
relevant-rules: []
release-via: publish
test-requirements: [unit, lint, typecheck]
labels: [observability, memory-guard, disk-pressure, fseventsd-plan]
---

# TRDD-1T53EKTN — Runaway-alert completeness (S6+S7)

## The task

Executes S6+S7 of the fseventsd plan (parent TRDD-ZNN0UK5K; sibling of the S5 detector
TRDD-HK7IZ21Z). Two observability gaps let the 39 GB fseventsd grow silently: (S6) the
daemon's `memory-guard` only KILLS janitor-owned runaways and stays silent about system
daemons it rightly won't kill; (S7) disk-pressure checks report only
`shutil.disk_usage().free` (writable-now), which contradicts the OS UI's
writable+purgeable number — alarming (or false-negativing) humans.

## Plan

- **S6** — add an ALERT path to `daemon.task_memory_guard`: when the victim selector finds
  a top-RSS process that `is_tier1_killable` REFUSES (system daemon, user session), emit a
  drift-line finding (`emit_once`-deduped, threshold env-tunable, default ≥4 GB RSS) instead
  of silence. Alert-only — the never-kill invariant is untouched.
- **S7** — one shared helper `disk_pressure()` returning BOTH numbers (writable-now via
  `shutil.disk_usage`; purgeable estimated on macOS via `diskutil info -plist /` APFS
  fields when available, else marked unknown). Report as `NN GB writable / +NN GB
  purgeable` in S5/S6 findings and any low-disk log (`screenshot-purge`,
  `trashcan-purge` disk checks). Fail-open: parse failure → writable-only, never crash.

## Derived tasks

- Coordinate the S5 detector (TRDD-HK7IZ21Z, backburner) to consume the same
  `disk_pressure()` helper — single source of truth, no per-detector reimplementation.
- Unit tests: killable-refused→alert, under-threshold→silent, dedupe, plist fixture parse,
  plist-missing fallback.

## Verification

- A synthetic 5 GB-RSS fake system process in the ps fixture yields exactly ONE alert line.
- Disk line matches the OS-UI semantics on this host (~writable + purgeable, TRDD-ZNN0UK5K
  forensics baseline); no alert claims "disk full" when purgeable covers it.
