---
trdd-id: KT0G5A43
title: Devitalize secret-shaped test values and credential examples in the janitor repo
column: dev
status: tasked
created: 2026-11-16T01:44:51+0100
updated: 2026-11-16T01:44:58+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: security
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-16T01:44:51+0100
---

# Devitalize secret-shaped test values and credential examples in the janitor repo

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-11-16

- NEXT ACTION: wave 1 (below) by Haiku workers, one file set each; then wave 2.
- Survey (read-only, 2026-11-16): trufflehog 385 unverified hits (10 in tracked files), gitleaks 15 (14 generic-api-key, 1 jwt) on the committed tree, about 128 secret-shape grep hits; none looked real in masked views, none verified against a live system. CPV `security` never completed (4 attempts, cause unknown; see TRDD-KCU6QCAP for the CPV pin). Raw survey: reports_dev/sonnet-worker/20261116_012853+0100-devitalize-survey.md (gitignored).

## Owner request (verbatim, 2026-11-15)

> devitalize all dangerous strings or secret patterns.

## Rule for every rewrite

A test value keeps its shape and length but is built at run time from tests/_fake_secrets.py (b62, hexs, secret, dsn), so no contiguous real-format secret sits in source. A docstring or comment example uses angle placeholders (`scheme://<user>:<password>@host`). Behaviour of every test stays the same: the touched test file passes before and after.

## Waves

1. Highest value: tests/test_jev_shadow_log.py (AWS-shaped keys, bearer, JWT); tests/test_env_detect.py, scripts/lib/env_detect.py, scripts/identify_environment.py (URL credentials); tests/test_web3_blockchain_patterns.py (a well-known public test private key); tests/test_sign_in_with_apple_patterns.py (EC key body); tests/test_secret_fixture_hygiene.py comment example.
2. Provider-prefix literals with fake bodies: tests/test_js_bundler_patterns.py, test_serverless_function_patterns.py, test_no_code_platforms_patterns.py, test_vite_esbuild_bun_patterns.py; then add an `sk-` marker to the hygiene guard. tests/test_oauth_rotator.py is excluded: rotator freeze (owner, 2026-11-05).
3. Docstring and comment URL-credential examples in scripts/lib/*_patterns.py, scripts/detectors/remote-credentials.py, skills/janitor-github-workflow-doctor/references/sentinel-rules-recipes.md, and the matching tests (to dsn()).
4. Secret shield TypeScript tests and the patterns.ts:149 comment, after report-sanitizer vendors the core (its card ZADXHV6W); then refresh the vendored copy with its sync script.
5. Prompt-injection sample phrases in test fixtures (22 files): assemble at run time. The recorded corpus tests/agent_context_bench/*.jsonl is not edited in place (a recording; recall-floor tests depend on it): decide regenerate or a load-time substitution, as in TRDD-KCU6QCAP.

## Approval log

- 2026-11-16T01:44:51+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-16T01:44:58+0100 — column → dev by main-agent@ai-maestro-janitor. owner goal 2026-11-15
