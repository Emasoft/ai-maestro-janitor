---
trdd-id: ZW0GUQCG
title: The shared marker rewriter closes frontmatter only on three dashes while the phrase fixer also accepts three dots
column: backburner
status: tasked
created: 2026-10-05T01:53:41+0200
updated: 2026-10-05T01:53:41+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T01:53:41+0200
---

# The shared marker rewriter closes frontmatter only on three dashes while the phrase fixer also accepts three dots

Found 2026-10-05 in the review of C15 (archived TRDD-9SUZ48E8). rewrite_markers in scripts/memgrep/src/fixers/quote_desc.rs (near line 109) ends the frontmatter only at a --- line; dedup_phrases.rs (near line 73) also accepts the YAML ... terminator. Effect, by reading (not measured): on a page whose frontmatter is closed by ..., the fixers that use rewrite_markers (quote_desc, dedup_keywords, superseded_move) treat the whole page as frontmatter and never edit it. That is fail-safe, but inconsistent. First step: measure with a ...-closed page whether lint itself reports atom findings there; if lint reports and the fixers decline, align rewrite_markers with the parser lint uses. rewrite_markers is shared by four fixers, so change it alone and re-run cargo test fixers.

## Approval log

- 2026-10-05T01:53:41+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
