---
trdd-id: SQBTMGYW
title: Slug-set resolver and single slug rule per language
column: backburner
status: tasked
created: 2026-10-23T17:56:59+0200
updated: 2026-10-23T17:57:52+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-23T17:56:59+0200
npt: [ICB4GTHI, 78GMFJB4, 0IJFCD2V, JE53ZDPS]
relevant-rules: [13, 14, 15, 24, 25]
spec: wikimem-layout-spec.md 0.2.3
---

# Slug-set resolver and single slug rule per language

Spec: design/specs/wikimem-layout-spec.md 0.2.3 (draft). Implements WL-3, WL-4, WL-5, WL-6. One shared slug rule per language (Python memory_scopes.project_slug, Rust memory.rs scope_project_slug, TypeScript in ai-maestro); fix the three deviating builders fleet_scan.py:969, fleet_status.py:322, identify_environment.py:348; build the per-session slug set (launch cwd, git toplevel membership, alias rule); search covers the set and writes go to the current session slug, worktree slugs included; change local_design_root in trdd_common.py:203-217 so worktree sessions stop writing to the main checkout slug. Anchors: memory_scopes.py:282-296, memory.rs:6747-6752, trdd_common.py:203-217. Done when: all builders route through the shared rule, the slug set is covered by real tests with symlinked and worktree paths, and worktree sessions write to their own slug folder.

## Approval log

- 2026-10-23T17:56:59+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
