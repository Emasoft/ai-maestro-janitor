---
trdd-id: AQ8IM083
title: Remove the ubsignore exclusion of the secret-shield patterns file once ubs converges on it
column: todo
status: tasked
created: 2026-11-14T00:48:05+0100
updated: 2026-11-14T00:49:45+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: infra
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-14T00:48:05+0100
---

# Remove the ubsignore exclusion of the secret-shield patterns file once ubs converges on it

## Approval log

- 2026-11-14T00:48:05+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Why

84f8fa7c added a root .ubsignore line, hooks/secret-shield/patterns.ts, because the ubs 5.4.17 JS taint analyzer (~/.local/share/ubs/modules/helpers/ubs_core/analyzers/taint_js.py) did not converge on that file: 12 GB RSS in 9 min in the pre-commit hook, then 'Partial run: js: error', which blocks every commit touching the file. A worker bisected it to redactUrlPasswords plus hasScheme analysed together; HEAD runs away too; the full-file cause is not localized. Causation is not isolated: the file last committed cleanly on 2026-11-05 (b3363706); taint_js.py changed 2026-11-10 and the hook 2026-11-09. Raw evidence: reports_dev/sonnet-worker/20261114_004229+0100-ubs-runaway.md. While the line exists, patterns.ts has NO ubs coverage in the pre-commit hook or a manual ubs run from the repo root (neither scripts/publish.py nor the workflows run ubs).

## Done when

A bounded run (kill the whole process tree at 2 GB RSS or 120 s, by recorded PID) of ubs on a directory holding only the current patterns.ts finishes with status ok; then the .ubsignore line (and the file, if empty) is removed and a commit touching patterns.ts passes the hook. If ubs never converges: the owner decides between keeping the exclusion, pinning or rolling back ubs, or a verified source reshape.
