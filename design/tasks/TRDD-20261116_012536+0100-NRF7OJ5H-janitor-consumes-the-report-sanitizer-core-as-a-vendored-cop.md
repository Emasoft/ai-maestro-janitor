---
trdd-id: NRF7OJ5H
title: Janitor consumes the report-sanitizer core as a vendored copy
column: backburner
status: tasked
created: 2026-11-16T01:25:36+0100
updated: 2026-11-16T01:25:36+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: refactor
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-16T01:25:36+0100
---

# Janitor consumes the report-sanitizer core as a vendored copy

## STATE — 2026-11-16
- NEXT ACTION: none until report-sanitizer finishes its merge (its card: Merge the janitor secret shield into report-sanitizer, increment 6 = swap). This tree's hooks/secret-shield/ stays upstream until then.
## Scope
1. hooks/secret-shield/{patterns.ts,rules/} become a vendored copy of report-sanitizer core/, pinned by hash, with a test.
2. CI install: .github/workflows/ci.yml:108-123 fetches sanitize_reports.py as one raw file pinned by SHA; after the swap the tool needs its core/ folder and bun, so CI installs bun and checks out the repo at a pinned commit.
3. The Python mini-redactors (scripts/lib/jev_shadow_log.py _redact_text, scripts/detectors/memory-scope-leak.py _SECRET_SHAPE_RE, scripts/daemon.py _masked_stderr_tail after checking what it serves) move to the CLI filter mode, one commit each. scripts/lib/oauth_rotator/reauth.py is excluded: rotator freeze (owner, 2026-11-05).
4. Upstream flip: report-sanitizer becomes upstream; scripts/lib/secret_names.py is generated from the core.
## Why
Owner goal 2026-11-15 (verbatim): "complete and improve the `~/Code/report-sanitizer` project, merging into it the secrets-shield code of the scanner, to create a powerful universal scanner and redactor."

## Approval log

- 2026-11-16T01:25:36+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
