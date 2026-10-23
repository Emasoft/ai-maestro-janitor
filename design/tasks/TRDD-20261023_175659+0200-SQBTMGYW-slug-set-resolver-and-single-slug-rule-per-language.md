---
trdd-id: SQBTMGYW
title: Slug-set resolver and single slug rule per language
column: blocked
status: tasked
created: 2026-10-23T17:56:59+0200
updated: 2026-10-23T18:03:45+0200
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
spec: wikimem-layout-spec.md 0.2.5
blocked-by: [W17F82DN]
pre-block-column: backburner
blocker-probe: trddgrep --design-dir /Volumes/EmaUITEK4TBSSD/Code/AI-MAESTRO-JANITOR/ai-maestro-janitor/design --porcelain show W17F82DN
blocker-holds-if: match:\t(backburner|blocked|todo|plan|dev|testing)\t
blocker-probe-canary: match:W17F82DN
---

# Slug-set resolver and single slug rule per language

Spec: design/specs/wikimem-layout-spec.md 0.2.5 (draft). Implements WL-3, WL-4, WL-5, WL-6, including the WL-4 decision table (one row per kind of launch-cwd evidence; join iff one member row and no join-blocking row), the remembered-state file in the LOCAL slug folder (adopted aliases, worktree paths seen, former nested repository paths, per-project path record; written atomically by the resolver only), and adoption by page project-id gated on VERIFY-4 (W17F82DN) and VERIFY-12 (JE53ZDPS). One shared slug rule per language (Python memory_scopes.project_slug, Rust memory.rs scope_project_slug, TypeScript in ai-maestro); fix the three deviating builders fleet_scan.py:969, fleet_status.py:322, identify_environment.py:348; build the per-session slug set (launch cwd, git toplevel membership, alias rule); search covers the set and writes go to the current session slug, worktree slugs included; change local_design_root in trdd_common.py:203-217 so worktree sessions stop writing to the main checkout slug. Anchors: memory_scopes.py:282-296, memory.rs:6747-6752, trdd_common.py:203-217. Done when: all builders route through the shared rule, the slug set is covered by real tests with symlinked and worktree paths, and worktree sessions write to their own slug folder.

## Approval log

- 2026-10-23T17:56:59+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-23T18:03:44+0200 — column → blocked. waits on W17F82DN
