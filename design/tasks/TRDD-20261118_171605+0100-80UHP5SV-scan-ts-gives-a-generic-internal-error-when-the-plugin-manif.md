---
trdd-id: 80UHP5SV
title: scan.ts gives a generic internal error when the plugin manifest is missing and SECRETS_SHIELD_SCAN_VERSION is unset
column: backburner
status: tasked
created: 2026-11-18T17:16:05+0100
updated: 2026-11-19T13:27:59+0100
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
approval-datetime: 2026-11-18T17:16:05+0100
---

# scan.ts gives a generic internal error when the plugin manifest is missing and SECRETS_SHIELD_SCAN_VERSION is unset

## Approval log

- 2026-11-18T17:16:05+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-19T13:27:59+0100 — the environment variable SECRETS_SHIELD_SCAN_VERSION was renamed SHIELD_SCAN_VERSION (scan.ts pluginVersion, tests/test_shield_scan_version.py, skills/janitor-secrets-shield-scan/SKILL.md): the CPV skillaudit rule CRED_ENV_READ (critical) matches process.env.[A-Z_]*SECRET and blocked the 3.9.9 publish gate on the old name (scan.ts:177). Any vendoring caller must set SHIELD_SCAN_VERSION, not the old name. By sonnet-worker for main-agent.

## Symptom

Measured 2026-11-18 on the vendored copy in report-sanitizer (no .claude-plugin/plugin.json there): with SECRETS_SHIELD_SCAN_VERSION unset, scripts/shield_scan/scan.ts exits 2 with only 'the scan stopped on an internal error'. Cause by code reading: pluginVersion() (scan.ts:175-183) calls readFileSync on PLUGIN_ROOT/.claude-plugin/plugin.json with no try, so the fs error leaves main() as a non-ScanError and the handler at scan.ts:511-517 prints the generic text. Fix: catch the read and throw a ScanError with a fixed text naming the missing manifest and the variable. Then report-sanitizer re-pins scripts/shield_scan (sync_core.py --pull). Low priority: the janitor always ships plugin.json and report-sanitizer's shield-scan command always sets the variable.
