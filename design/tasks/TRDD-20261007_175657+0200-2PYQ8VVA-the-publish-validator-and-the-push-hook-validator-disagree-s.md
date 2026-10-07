---
trdd-id: 2PYQ8VVA
title: The publish validator and the push-hook validator disagree, so a nit fails only after the bump
column: todo
status: tasked
created: 2026-10-07T17:56:57+0200
updated: 2026-10-07T20:35:05+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T17:56:57+0200
---

# The publish validator and the push-hook validator disagree, so a nit fails only after the bump

On 2026-10-07 the 3.8.8 publish's step-4 validator passed card 58Q791FL, but the push hook's validator run refused the push on markdownlint MD028 (blank line between two blockquotes) in that card, after the version bump commit and tags existed locally. Find why the two runs lint different file sets or rules, and make step 4 run exactly what the push hook runs, so a nit fails before the bump. Also: worker briefs that write cards should run markdownlint on the card.

## Approval log

- 2026-10-07T17:56:57+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Findings 2026-10-07

Measured (log reports/publish/20261007_162213+0200-publish-patch.log): the two validator command lines are IDENTICAL, uvx --from git+https://github.com/Emasoft/claude-plugins-validation@v5.16.2 --with pyyaml cpv-remote-validate plugin . --strict (scripts/publish.py:1801-1814 step 4, and :1488-1496 push-gate G3), same cwd, pin and strictness; no env differs.
The difference is inside CPV: in step 4 (log line 423) CPV printed 'WARNING markdownlint timed out - skipping markdown lint' (and a pyright timeout, line 424), so the lint never ran and SUMMARY showed NIT=0 (line 826). In the G3 run markdownlint completed and reported NIT MD028 (log lines 4983, 5385). CPV downgrades its own markdownlint timeout to a WARNING, which --strict passes, under heavy load right after the test stage.
No code change here: a shared command builder changes nothing because the commands already match. CPV side must change: under --strict a linter timeout must be a blocking finding, or CPV must raise and expose its markdownlint timeout. Optional follow-up here, not done: fail step 4 when CPV output contains 'timed out - skipping'.
