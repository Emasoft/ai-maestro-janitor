---
trdd-id: F3AUDLOG
title: Immortality F3 — recovery audit log (append-only NDJSON) + F2 dashboard augments
column: dev
created: 2026-06-25T08:40:10+0200
updated: 2026-06-25T08:40:10+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 4
severity: LOW
effort: S
labels: [immortality, observability, fleet-guardian, audit-log, group-f]
task-type: feature
parent-trdd: TRDD-324223a6
relevant-rules: []
release-via: publish
delivery: pull-request
target-branch: main
test-requirements: [unit]
runtime-targets: [macos, linux]
impacts: []
external-refs: []
---

# TRDD-F3AUDLOG — immortality F3: recovery audit log + F2 dashboard augments

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-25

### Status: dev — the ONE safe, genuinely-missing GROUP F gap the E+F eval found (the other gap, E2/E3, is the process-KILLING TRDD-56d24c02, HELD for explicit USER opt-in). Pure observability, ZERO blast radius. Building autonomously.

- **THE EVALUATION (durable artifact — read before acting):**
  `reports/immortality-group-ef/20260625_083745+0200-group-ef-scope-eval.md` (the F3 + F2 rows, file:line).
  Verdict: GROUP E+F are ~88% already built; E1/E4/E5/E6/F1/F4 EXISTS-ALREADY or NOT-APPLICABLE-as-drafted.
  Two real gaps: E2/E3 (= TRDD-56d24c02, held) and THIS (F3 + F2-augments).

- **THE GAP:** the daemon writes ONLY per-instance recovery *state* (`{attempts,last_ts,identity,alerted}` at
  `<global_state>/recovery/<slug>`) and **overwrites it every beat** (`daemon.py` `_recovery_state_path` /
  `_read_recovery_state` / `_write_recovery_state` ~:651-678, written ~:711-771). FIRE outcomes go only to the
  rotating, unstructured `dispatch`/daemon TEXT logs (`daemon.py:774-778`). So *"which rung fired, on which
  session, when, with what outcome — historically"* is UNANSWERABLE. No append-only, queryable record exists.

- **NEXT ACTION (two parts, both small + safe):**

  **Part 1 — F3 recovery audit log.** In `daemon.task_session_liveness`, on EVERY recovery decision
  (fired / declined / dry-run / crash-loop-tripped), append ONE structured record
  `{ts, project_root, pid, tty, diagnosis, rung, channel, outcome}` to a new
  `<global_state>/recovery-audit.ndjson`. **REUSE the existing `janitor_self_integrity.AuditChain` HMAC-NDJSON
  primitive** (tamper-evident, append-only, already tested — do NOT invent a new log format). Cap/rotate the file
  like `token_meter.trim_log` (bounded size, oldest-trimmed). **FAIL-OPEN, MANDATORY:** the audit-append is wrapped
  so a logging fault (disk-full, HMAC key missing, AuditChain raise) can NEVER break or even perturb the recovery
  beat — the beat's actual recovery logic is untouched; the audit is a pure side-channel. (The daemon loop is
  brick-risk: the append must be try/except-guarded exactly like the C4 rollback producer.)

  **Part 2 — F2 dashboard augments.** Extend `scripts/fleet_status.py` (the `/janitor-show-global-status` backing)
  to surface three READ-ONLY signals it already has the libs for but doesn't show: (a) **OS-keepalive registration**
  via `launchd_keepalive.is_installed()`; (b) **self-integrity manifest verdict** via
  `janitor_self_integrity.verify_manifest(...)` (fail-open: render "unknown" if no manifest/key, never crash the
  dashboard); (c) a **last-N-recoveries rollup** read from the new `recovery-audit.ndjson`. All read-only additions
  to the existing dashboard, not a new command.

- **Load-bearing constraints:**
  - FAIL-OPEN everywhere (audit-append never breaks the beat; dashboard reads never crash on missing files/keys).
  - REUSE `AuditChain` (don't reinvent); REUSE `trim_log`-style rotation (don't reinvent).
  - The audit log is pure observability — it RECOVERS nothing, so it carries no recovery-correctness risk.

## Scope guards / non-goals
- Do NOT touch the recovery LOGIC (the ladder, is_killable, the gates) — only ADD a side-channel audit + dashboard reads.
- Do NOT wire the hard-restart rungs — that is E2/E3 (TRDD-56d24c02), HELD for explicit USER opt-in (destructive).
- Do NOT build a real-time fs-watcher (F1) — the eval ruled it LOW-value vs the existing 2-min beat.

## Why this exists
F3 is the one genuinely-missing, genuinely-valuable, SAFE GROUP F gap: a human cannot today answer "is the
guardian working / what did it do / why is it crash-looping" because recovery history is overwritten every beat.
This adds the tamper-evident forensic record (reusing AuditChain) + surfaces it + the keepalive/integrity verdicts
in the existing dashboard — the observability half of "immortal", with no blast radius.
