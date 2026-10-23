---
trdd-id: SQBTMGYW
title: Slug-set resolver and single slug rule per language
column: blocked
status: tasked
created: 2026-10-23T17:56:59+0200
updated: 2026-10-23T20:26:27+0200
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
spec: wikimem-layout-spec.md 0.2.9
blocked-by: [KQULEGL2]
pre-block-column: backburner
blocker-probe: trddgrep --porcelain show KQULEGL2
blocker-holds-if: match:\t(backburner|approval|design|design_ai_review|design_human_review|todo|verify_assumptions|plan|dispatch|dev|testing|ai_review|human_review|blocked|failed|proposal|planned)\t
blocker-probe-canary: match:KQULEGL2
---

# Slug-set resolver and single slug rule per language

Spec: design/specs/wikimem-layout-spec.md 0.2.9 (draft). Implements WL-3, WL-4, WL-5, WL-6, including the WL-4 decision table (one row per kind of launch-cwd evidence; join iff one member row and no join-blocking row), the remembered-state file in one file under the slug of the main worktree's toplevel realpath, append-only under an exclusive lock (adopted aliases, worktree paths seen, former nested repository paths, per-project path record; written by the resolver only), and adoption by page project-id gated on VERIFY-4 (W17F82DN) and VERIFY-12 (JE53ZDPS). One shared slug rule per language (Python memory_scopes.project_slug, Rust memory.rs scope_project_slug, TypeScript in ai-maestro); fix the three deviating builders fleet_scan.py:969, fleet_status.py:322, identify_environment.py:348; build the per-session slug set (launch cwd, git toplevel membership, alias rule); search covers the set and writes go to the current session slug, worktree slugs included; change local_design_root in trdd_common.py:203-217 so worktree sessions stop writing to the main checkout slug. Anchors: memory_scopes.py:282-296, memory.rs:6747-6752, trdd_common.py:203-217. Done when: all builders route through the shared rule, the slug set is covered by real tests with symlinked and worktree paths, and worktree sessions write to their own slug folder. Acceptance: the WL-4 errata E1-E5 in the spec, each as a test written before the resolver code. The blocker-probe covers only the first blocked-by id; release requires every blocked-by id to be terminal. Also: a tie-blocked folder (E3) is listed in the resolver's report, which is the resolver command's output: one line per unknown, shared or tie-blocked folder, with its reason. A human overrides a folder with a resolver command (for example `memgrep slugs force-join <folder>` or `force-block`), which writes the override line itself under the exclusive lock, so the file keeps a single writer (WL-4). An override line beats every row of the decision table, E3 ties included, and is undone by a third resolver command (for example `memgrep slugs clear-override <folder>`) that writes the revoking line under the same lock; every revoking line, including one that undoes a wrong adoption, is written by a resolver command, never by hand. Test: the report lists a tie-blocked folder; after the override command, the folder joins, or stays blocked, on the next run; after clear-override, it returns to the decision table's result. E3's "searchable by its own sessions" means the sessions launched in that folder (E2), not every session of the project.

## Approval log

- 2026-10-23T17:56:59+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-23T18:03:44+0200 — column → blocked. waits on W17F82DN
- 2026-10-23T20:26+0200 — ACCEPTANCE ADDED (main session, review of 26196af6): SCOPE (corrected by the review of ab750bef): adoption of a page by its project-id is out of scope for this card, with no disabled code path; it lands with TRDD-W2PH88JQ after TRDD-AAZUB0VC writes the project-id rule. The rest of the resolver does not depend on that rule.
