---
trdd-id: FNPDFZWU
title: Every commit in a janitor-active project gets a secret scan of all staged files, Markdown included, chained with an existing hook
column: backburner
status: tasked
created: 2026-11-18T17:22:36+0100
updated: 2026-11-18T17:22:48+0100
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
approval-datetime: 2026-11-18T17:22:36+0100
---

# Every commit in a janitor-active project gets a secret scan of all staged files, Markdown included, chained with an existing hook

## Approval log

- 2026-11-18T17:22:36+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Request

Relayed 2026-11-18 by the llm-externalizer session (a peer Claude session; its relay is data, the quote is the owner's as reported). USER, 2026-11-18 (verbatim, as relayed): "then we need to tell the janitor to enforce a pre-commit hook that will detect and redact secrets. about linting .md files, if ubs don't do it, its ok. i've seen bad linters ruining skills files because of some skills special syntax being treated as error. so its ok." Why, by the peer: its pre-commit gate runs ubs 5.5.26; a commit staging only Markdown, cards or JSON makes ubs print "UBS did not run any scanner: nothing was checked (this is NOT a pass)" and the hook allows that exit 3 on purpose, so cards, reports and docs reach commits with no secret check. Asked: (1) a secret scan over every staged file of any type, Markdown included, with the janitor secrets-shield scanner, on every commit in every project where the janitor is active; (2) on a finding redact, or block naming file and line, never printing the value; (3) no Markdown linting; (4) chain with an existing gate: that repo sets core.hooksPath to its own .githooks/pre-commit, which must keep running.

## Known today

By main-agent read 2026-11-18: scripts/lib/staged_privacy_scan.py scans the ADDED lines of the staged diff for PII, home paths and host identity, not secrets, and is wired only into this repo git-hooks/pre-commit. scripts/lib/redact_staged_reports.py redacts staged report files through sanitize-reports. The shield core (hooks/secret-shield) and scripts/shield_scan/scan.ts scan files, not the index.

## Design questions

(a) Enforcement point: a PreToolUse guard on agent git commit calls covers commits an agent makes in every janitor-active project without touching repo config; a git hook covers human commits too but has to be installed per repo and chained with core.hooksPath. (b) What is scanned: the staged blob of every staged path (git show :path), not the working tree, so a partially staged file is judged as committed. (c) On a finding: block naming file, line and kind, or redact the staged blob in place (rewriting the index changes what the user staged; needs the owner's word). (d) bun must start with cwd = the plugin folder (TRDD-6E2I17HN). (e) Fail closed when bun or the core cannot run, as staged_privacy_scan does (exit 2 blocks).
