---
trdd-id: NRF7OJ5H
title: Janitor consumes the report-sanitizer core as a vendored copy
column: todo
status: tasked
created: 2026-11-16T01:25:36+0100
updated: 2026-11-16T04:59:04+0100
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
- NEXT ACTION: none until report-sanitizer finishes its merge (its card ZADXHV6W in the report-sanitizer repo: Merge the janitor secret shield into report-sanitizer, increment 6 = swap). This tree's hooks/secret-shield/ stays upstream until then.
- 2026-11-16 (main agent): report-sanitizer feat/shield-core (TRDD-ZADXHV6W there) is ready to merge; it now spawns bun for every redaction. Janitor consequences: (1) tests/test_redact_staged_reports.py needed `bun` in its real_subprocess markers, or the sandbox guard (tests/sandbox_guard.py:703) blocks the spawn and 2 of 5 tests fail; added in the same commit as this line. (2) The CI step "Install sanitize-reports (pinned)" (ci.yml, SANITIZER_SHA 16c9a12) fetches ONE raw file; a pin bump past the merge must fetch the whole tree (core/, shield_bridge.ts) and install bun, or every real run exits 4. (3) Upstream to hooks/secret-shield: dckr_pat_/dckr_oat_ tokens, Maven <password>/<passphrase> literals and letters-only npmrc :_authToken literals, which report-sanitizer now closes in its Python layer (its commit 54ce571).
## Scope
1. hooks/secret-shield/{patterns.ts,rules/} become a vendored copy of report-sanitizer core/, pinned by hash, with a test.
2. CI install: .github/workflows/ci.yml:108-123 fetches sanitize_reports.py as one raw file pinned by SHA; after the swap the tool needs its core/ folder and bun, so CI installs bun and checks out the repo at a pinned commit.
3. The Python mini-redactors (scripts/lib/jev_shadow_log.py _redact_text, scripts/detectors/memory-scope-leak.py _SECRET_SHAPE_RE, scripts/daemon.py _masked_stderr_tail after checking what it serves) move to the CLI filter mode, one commit each. scripts/lib/oauth_rotator/reauth.py is excluded: rotator freeze (owner, 2026-11-05).
4. Upstream flip: report-sanitizer becomes upstream; scripts/lib/secret_names.py is generated from the core.
## Why
Owner goal 2026-11-15 (verbatim): "complete and improve the `~/Code/report-sanitizer` project, merging into it the secrets-shield code of the scanner, to create a powerful universal scanner and redactor."

## Approval log

- 2026-11-16T01:25:36+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-16T04:58:34+0100 — column → todo. holds three live obligations after the 3.9.4 sanitizer swap

## Progress

2026-11-16: a re-probe of the live shield confirmed three gaps (bare dckr_pat_/dckr_oat_ tokens, Maven <password>/<passphrase> values, scoped npmrc :_authToken values without the npm_ prefix); the upstream rules are being written by the shield-gaps worker.
