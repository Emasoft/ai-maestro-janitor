---
trdd-id: DMH25CYD
title: Compact hold reports its selected waiting signal and conditional expiry
column: todo
status: tasked
created: 2026-10-13T23:06:59+0200
updated: 2026-10-13T23:07:44+0200
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
