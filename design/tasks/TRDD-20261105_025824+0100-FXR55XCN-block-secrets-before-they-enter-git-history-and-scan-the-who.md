---
trdd-id: FXR55XCN
title: Block secrets before they enter git history and scan the whole history
column: todo
status: tasked
created: 2026-11-05T02:58:24+0100
updated: 2026-11-05T03:11:24+0100
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
approval-datetime: 2026-11-05T02:58:24+0100
---

# Block secrets before they enter git history and scan the whole history

Derived from TRDD-RPHJ64W1. Measured 2026-11-05: git-hooks/pre-commit (45 lines) runs a privacy scan whose documented checks (scripts/lib/staged_privacy_scan.py:3-20) are personal e-mails, home paths and machine identity, PII shapes and this host's username and hostname; none of them is a credential or token format rule (from that docstring; scripts/lib/private_path_patterns.py and the publish.py G1b lint were not read); git-hooks/pre-push:90-113 scans feature-branch pushes only with trufflehog and refuses when trufflehog is missing; scripts/publish.py has no trufflehog or gitleaks call of its own (grep), and whether its CPV --strict stage secret-scans the commits it pushes is unverified. Plan: a staged-diff secret scan added to pre-commit as its own stage next to the privacy scan, fail-closed like pre-push:90-97, engine trufflehog; a full-history scan (trufflehog git file://<repo>, plus the reflog) whose report masks every value; a history rewrite exists only as a printed plan: rotate the secret first, mirror-clone backup, fresh clone, git filter-repo --replace-text, rescan, human force-push with --force-with-lease, collaborators re-clone (ideas: mogesjohnson_history-scrub plan.ts:51-76; gotchas from nikolareljin_leak-lock git-rewrite.js: refs/replace aliases, remote-only branches, filter-repo removes origin). Any rewrite or force-push runs only on an exact command the owner approves (RULE 0 of the owner's global rules). Both history-scrub and leak-lock are on the corpus neutralized list: ideas only, no code.

## Done when
 - [ ] Before building the pre-commit scan, confirm from trufflehog --help or its docs that the chosen invocation sees staged but uncommitted content (its documented pre-commit recipe scans commits since HEAD); if it does not, scan an export of the index with trufflehog filesystem. Then pre-commit blocks a commit that stages a test secret, and refuses when trufflehog is missing (tests).
 - [ ] Whether publish.py scans for secrets before a default-branch push is checked, and any gap is closed.
 - [ ] A full-history scan of this repo has run, with whether trufflehog also reads the reflog and unreachable objects verified first (if not, they are scanned another way); its masked report gives each finding a card.
 - [ ] The plan generator prints the rewrite plan and never runs it (test).
 - [ ] trufflehog --json prints the raw secret value; every report this card writes masks each value before writing, shown by a test.
 - [ ] The time the new stage adds to a commit is measured, and the trufflehog requirement is documented where publish.py installs the hooks (install_hook).
 - [ ] The secret shapes the existing privacy stage already catches are listed from its code, including private_path_patterns.py and the publish.py G1b lint.
 - [ ] trufflehog findings on the repo's own fixtures and cards (the secret-shield tests and cards name token shapes) are measured, and handled without an allow-list that could hide a real secret.

## Approval log

- 2026-11-05T02:58:24+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
