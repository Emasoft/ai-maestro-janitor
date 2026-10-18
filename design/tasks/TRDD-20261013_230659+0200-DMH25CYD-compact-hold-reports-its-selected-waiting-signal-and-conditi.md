---
trdd-id: DMH25CYD
title: Compact hold reports its selected waiting signal and conditional expiry
column: testing
status: tasked
created: 2026-10-13T23:06:59+0200
updated: 2026-10-18T03:49:40+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-13T23:06:59+0200
relevant-rules: [5, 6]
implementation-commits: [0e131aa8, 815acb25]
---

# Compact hold reports its selected waiting signal and conditional expiry

## Task

Resolve GitHub issue #340 with diagnostics only. Preserve waiting predicate order, clocks, recovery guards, daemon-coverage exemption and every safety veto including --force restrictions. Evaluate the shared waiting evidence once; retain the boolean interface for existing callers. Report the selected blocking signal and its known conditional expiry in manual verdict output, not raw directives or agent identifiers. Recovery flags have unknown time-based expiry. A selected signal expiry does not guarantee the entire hold ends. Explain the 30-minute timestamp windows versus consumption-based recovery in the compact-context skill.

## Acceptance

- [ ] Focused tests verify resume and directive expiry, agent attribution, daemon suppression and unchanged force vetoes.
- [ ] Verdict reports selected signal and conditional or unknown expiry without leaking directive text or agent identifiers.
- [ ] Skill explains timestamp windows and that another veto can remain.
- [ ] Ruff, mypy, pyright and the full test suite pass.

## Constraints

PRRD S5.1 forbids suppressing validation to pass the gate; PRRD S6.1 requires preserving detector failure behavior. No new persistent state or safety-policy change.

## Approval log

- 2026-10-13T23:06:59+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## STATE

2026-10-17 impl (uncommitted, pending orchestrator commit): dispatch._active_waiting_signal returns (kind, expiry_text); _cadence_active_waiting is its boolean wrapper; external_handoff_clear._decide calls the signal once, facts[waiting_signal] only; VERDICT line adds waiting=<kind>, <expiry> when why=active-waiting; compact-context SKILL.md names the four signals and the 30-minute windows. Tests: new test_active_waiting_signal.py (15) plus 2 handoff tests; 392 passed across the six named files; ruff, mypy, pyright clean on changed files; full suite not run. recovery-flag is unreachable in the VERDICT line (recovery gate runs first), covered at function level only. Out of scope: issue suggestion 3.
