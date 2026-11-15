---
trdd-id: W5GXPT7T
title: Remove the temporary reports gitignore line once CPV stops requiring it
column: backburner
status: tasked
created: 2026-11-15T09:10:44+0100
updated: 2026-11-15T09:10:44+0100
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
approval-datetime: 2026-11-15T09:10:44+0100
---

# Remove the temporary reports gitignore line once CPV stops requiring it

Temporary .gitignore line /reports/ added for the 2026-11-15 release. CPV --strict (pin v5.16.2; the same rule in v5.23.0, scripts/validate_plugin.py EXPECTED_GITIGNORE_CATEGORIES) raises a MAJOR unless reports/ is gitignored, while TRDD-KSUIEPTQ and the owner rule (2026-11-01, restated verbatim 2026-11-15) keep reports/ git-tracked. Upstream request: https://github.com/Emasoft/claude-plugins-validation/issues/275. Done when: a CPV release drops the reports/ MAJOR; this repo's .cpv-version pin moves to it (its own card, it brings new rules); the /reports/ line and its comment are removed from .gitignore; cpv-remote-validate --strict passes without it. Known cost while the line exists: the janitor-doctor gitignore check reports FAIL for a /reports/ line (tests/test_doctor_gitignore_reports.py:55), and new final reports need git add -f.

OWNER DECISION (verbatim, AskUserQuestion, 2026-11-15). Question: 'The release is blocked by one MAJOR finding from CPV --strict, the plugin validator that publish.py runs as a gate. CPV 5.16.2 requires `reports/` to be gitignored, and so does 5.23.0, the latest. Your rule of 2026-11-15 and TRDD-KSUIEPTQ say `reports/` stays git-tracked. Everything else passes, and the second blocker is a one-line format fix already being applied. How should I unblock the release?' Answer: 'Ignore now, revert later (Recommended)'. That option's stated plan: 'Add `/reports/` to .gitignore for this release. Files already tracked stay tracked, but new final reports need `git add -f`. File an issue on Emasoft/claude-plugins-validation asking CPV to require only `reports_dev/` ignored, plus a card to remove the line once CPV changes. The clear-loop fix (TRDD-8ZY3JU2H) ships today.' Correction to the question: 'Everything else passes' was too strong; at that time the shield speed test, the full pytest suite, jscpd, actionlint and the CI preflight had not run on HEAD, and the format fix had not been applied.

## Approval log

- 2026-11-15T09:10:44+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
