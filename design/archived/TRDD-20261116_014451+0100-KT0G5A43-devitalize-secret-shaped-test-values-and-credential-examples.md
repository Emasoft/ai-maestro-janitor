---
trdd-id: KT0G5A43
title: Devitalize secret-shaped test values and credential examples in the janitor repo
column: complete
status: archived
created: 2026-11-16T01:44:51+0100
updated: 2026-11-16T02:56:04+0100
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

- DONE 2026-11-16: waves 1, 2, 4 and 5 committed (2ac37881, 20abebaf, 010f04c5, 058979bf, 728bf64a); wave 3 skipped by decision (below). No next action on this card.
- Survey (read-only, 2026-11-16): trufflehog 385 unverified hits (10 in tracked files), gitleaks 15 (14 generic-api-key, 1 jwt) on the committed tree, about 128 secret-shape grep hits; none looked real in masked views, none verified against a live system. CPV `security` never completed (4 attempts, cause unknown; see TRDD-KCU6QCAP for the CPV pin). Raw survey: reports_dev/sonnet-worker/20261116_012853+0100-devitalize-survey.md (gitignored).
- Wave 3 skipped: its 34 URL-credential examples (21 in scripts, skills and docs, 13 in tests) use placeholder passwords such as `pass` or an ellipsis; trufflehog and gitleaks flag none and the hygiene test allows them. Only env_detect.py:84 and identify_environment.py:250 became `<user>:<password>` (20abebaf).
- Wave 5 measured with the janitor's own guards on the 12 changed files (before vs after 728bf64a): ai_jailbreak_patterns 216 -> 169 findings; agent_config_patterns (prose) 208 -> 208; prompt_injection_patterns 52 -> 52. A one-line probe (2026-11-16) shows why: agent_config_patterns flags the phrase split or not (1 finding each), prompt_injection_patterns flags neither form (its 52 come from other fixture content), ai_jailbreak_patterns flags only the contiguous form. These files are the detectors' own fixtures; splitting inside words was not done.
- Left as is, by decision: the recorded corpora tests/agent_context_bench/*.jsonl and its reports/ (AWS documentation example keys, a JWT header fragment, low-entropy placeholders and the benchmark's own injection payloads; recall-floor tests pin them; corpus.jsonl already expands {{FAKESECRET}} at load time); the fuzz piece at hooks/secret-shield/tests/patterns.test.ts:2657; the sk-ant-oat01- prefix in the hygiene markers (its only fixture is in the frozen rotator tests, owner freeze 2026-11-05).
- Scans 2026-11-16 of the 13 changed non-card files of waves 1-4: gitleaks exit 0, no leaks; trufflehog exit 0 with one unverified SQLServer match whose raw value is the placeholder letter V in the test-case labels `Password=V;` (patterns.test.ts:2110-2114), inert. UBS still reports 29 critical hardcoded-secrets in patterns.test.ts: a variable-name heuristic, advisory in pre-commit. The hygiene test now blocks contiguous sk-ant-api/admin and sk-proj- keys (010f04c5).
- Wave 5 grep scope: *.py, *.ts, *.md, *.sh and *.json under tests/, scripts/, hooks/ and skills/, benchmark corpora excluded; contiguous phrases were in 12 files. The earlier 22-file figure came from the survey's broader match and was not re-derived. UBS on 728bf64a: 1 advisory critical (python.ctcompare.secret_eq at tests/test_dispatch_phases.py:4674), a line the wave did not touch. Wave 4's vendored-core refresh: report-sanitizer 492aafe re-pins core/ to 058979bf.

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
- 2026-11-16T02:56:04+0100 — COMPLETE by main-agent@ai-maestro-janitor. waves 1, 2, 4, 5 committed and verified; residue recorded in STATE; acceptance boxes checked.

## Acceptance

- [x] Waves 1, 2, 4 and 5 committed (2ac37881, 20abebaf, 010f04c5, 058979bf, 728bf64a); each touched test file passes before and after.
- [x] gitleaks and trufflehog over the touched non-card files of waves 1-4 find no leak; the one inert trufflehog placeholder match is recorded in STATE.
- [x] The fixture hygiene test blocks contiguous sk-ant-api, sk-ant-admin and sk-proj- keys (010f04c5).
- [x] The report-sanitizer vendored shield core is re-pinned to 058979bf (report-sanitizer 492aafe).
- [x] Every residue left by decision is named in STATE with its reason (wave 3, corpora, fuzz piece, sk-ant-oat01-, UBS heuristic).
