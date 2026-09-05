---
name: janitor-detector-and-hook-roster
description: "the janitor detector and hook roster split into parts / how many janitor detectors are there / full list of the janitor detectors by group / what are the 16 janitor hooks / where do detector coverage and false-positive measurements live / how good is a security detector really / does agent-context-integrity actually catch poisoning / which detectors cover supply-chain security / which detectors watch for scope drift / the cleanup and observability detector groups / what does the github-issues-watch detector do / what does gh-reply-watch do / boundedness invariants for self-healing loops"
ocd: 2026-08-02
lmd: 2026-09-05
metadata:
  node_type: memory
  type: reference
  tier: hub
  functionality: detector-and-hook-roster
publish-globally: false
split-lineage: c4529390a94648e49f74f86799cd937b
---

# janitor-detector-and-hook-roster

The janitor's full detector-and-hook inventory, split across two pages once the
single-page roster outgrew the split cap: the grouped detector/hook/pattern-library
listing itself, and the measured effectiveness findings (coverage, false-positive
rate, and specific detector bugs) discovered while auditing that listing.

## Parts

- [[janitor-detector-and-hook-roster-list]] — the full grouped detector roster
  (git/workflow hygiene, TRDD/task, cleanup, observability, scope drift, memory,
  supply-chain/security, updates groups), the boundedness invariants, the
  pattern-library conventions, and all 16 janitor hooks.
- [[janitor-detector-and-hook-roster-findings]] — measured coverage/false-positive
  rates for `agent-context-integrity`, the recurring regex-matching-mechanics
  failure shapes behind them, the `gitignore-coverage` and `project-map-drift`
  bug write-ups, and the CLAUDE.md poisoning-vector analysis.

## Governed by

- [[janitor-architecture]] — the architecture hub; this page is the detailed roster
  behind its abbreviated detector/pattern-library/hooks summaries.

## Notes and lessons learned
