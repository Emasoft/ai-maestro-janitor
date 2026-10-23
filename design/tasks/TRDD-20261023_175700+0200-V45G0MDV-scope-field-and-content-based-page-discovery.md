---
trdd-id: V45G0MDV
title: Scope field and content-based page discovery
column: backburner
status: tasked
created: 2026-10-23T17:57:00+0200
updated: 2026-10-23T18:08:10+0200
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
approval-datetime: 2026-10-23T17:57:00+0200
npt: [QNDPNJZN]
relevant-rules: [13, 14, 17, 19]
spec: wikimem-layout-spec.md 0.2.8
---

# Scope field and content-based page discovery

Spec: design/specs/wikimem-layout-spec.md 0.2.8 (draft). Implements WL-7, WL-8, WL-9. Every wikimem page carries scope: local|project|user; a file is a wikimem page iff its frontmatter holds node_type or tier (is_curated_wiki_page, memory_scopes.py:792-830); memgrep finds pages anywhere under a scope root; a missing scope is derived from the path and lint autofixes it; the field wins over location except that a local or user page git would track is refused and reported. Anchors: memory.rs:6787 scope_layer, memory_scopes.py:792-830. Done when: discovery is by content, lint autofixes scope, and the tracked-local-page refusal is tested for real.

## Approval log

- 2026-10-23T17:57:00+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
