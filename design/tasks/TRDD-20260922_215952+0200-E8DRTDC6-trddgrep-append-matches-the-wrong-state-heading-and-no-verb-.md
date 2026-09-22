---
trdd-id: E8DRTDC6
title: trddgrep append matches the wrong STATE heading and no verb deletes a frontmatter field
column: backburner
created: 2026-09-22T21:59:52+0200
updated: 2026-09-22T21:59:56+0200
current-owner: ai-maestro-janitor main session
created-by: ai-maestro-janitor main session
task-type: bugfix
min-approval-requirement: none
assignee: ai-maestro-janitor main session
mandate: true
mandated-by: user
approved: true
approval-judge: ai-maestro-janitor main session
approval-datetime: 2026-09-22T21:59:52+0200
---

# trddgrep append matches the wrong STATE heading and no verb deletes a frontmatter field

Observed 2026-09-22 while editing L32WC0H7. trddgrep append <id> "## STATE — READ THIS FIRST ON RESUME" <line> created a second ## STATE section instead of appending into the existing heading (the heading carries a trailing "(authoritative; supersedes the body) — <date>" suffix the matcher does not tolerate). And there is no verb to delete a field or a line: clearing review-after: left an empty, grammar-violating "review-after: " value (rule 4: no trailing whitespace; field grammar YYYY-MM-DD) that had to be removed by hand via the Edit tool. Expected: append matches a heading by prefix or offers --heading-line N; set <id> <field> --unset (or an unset verb) removes a field cleanly; validate flags an empty date field.

## Approval log

- 2026-09-22T21:59:52+0200 — MANDATE issued by ai-maestro-janitor main session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
