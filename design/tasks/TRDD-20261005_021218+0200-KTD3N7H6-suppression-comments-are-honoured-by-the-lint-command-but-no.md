---
trdd-id: KTD3N7H6
title: Suppression comments are honoured by the lint command but not by the write gate or the fixer oracle
column: backburner
status: tasked
created: 2026-10-05T02:12:18+0200
updated: 2026-10-06T20:14:54+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T02:12:18+0200
---

# Suppression comments are honoured by the lint command but not by the write gate or the fixer oracle

Found 2026-10-05 while reviewing C21 (TRDD-3HLI7DMK). Facts read in source. C21 applies noqa comments and the frontmatter lint-ignore key in apply_lint_config, which runs only in the memgrep lint command; lint_page_text is unchanged. Consequences: (1) a finding suppressed in lint still blocks a write, because the write gate (pre_write) uses lint_page_text; lint and the gate disagree by design, the same class as janitor issue 227. (2) lint_page_text never emits unused-noqa, so the has_code unused-noqa assert in scripts/memgrep/src/fixers/unused_noqa.rs can never fail; archived card TRDD-RUJQ7WSX says that limit lasts until C21, which is no longer true. (3) unused-noqa is emitted for selectors of cross-page rules (WMLINK, MGPERF, atom-dup-id) even when one file is linted, where the other half of the finding is out of scope; the C19 fixer refuses to judge those through a predicate page_decidable that is private to the fixer module and belongs in the rule registry. (4) lint autofixes before reporting by default, so a suppression covering a finding that was just autofixed is reported as unused. No page in the PROJECT or USER memory carries a suppression today (checked 2026-10-05), so nothing fires yet. Owner of the decision: C22 (TRDD-JD2QR5SQ), which wires the fixers into lint and must make emitter, fixer and gate agree. First step: decide whether noqa is a lint-time concept only (then say so in the spec and fix the oracle) or a property of lint_page_text.

## Approval log

- 2026-10-05T02:12:18+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## STATE

2026-10-06 DECISION (taken by C22, TRDD-JD2QR5SQ): suppression is a lint-command concept only; lint_page_text, the write gate and the fixer oracle stay raw, because a comment inside a page must not waive a gate-floor error on a write. Known cost: lint can exit 0 on a suppressed floor finding that every write verb still refuses. Follow-ups left on this card: lint prints a note when a suppressed finding is a gate-floor rule; the spec states the disagreement; unused-suppression selectors of cross-page rules.
