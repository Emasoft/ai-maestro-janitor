---
trdd-id: XI9UYD4E
title: memgrep update-mem-atom cannot desc-edit a footnote-lesson atom (stdin body mandatory even for empty body spans)
column: testing
status: tasked
created: 2026-09-25T17:39:50+0200
updated: 2026-09-25T21:29:34+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-09-25T17:39:50+0200
---

# memgrep update-mem-atom cannot desc-edit a footnote-lesson atom (stdin body mandatory even for empty body spans)

## Approval log

- 2026-09-25T17:39:50+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-09-25T21:29:34+0200 — column → testing by main-agent@ai-maestro-janitor. implemented + migration completed; 441 memgrep tests green

## STATE

2026-09-25 21:40 — implemented: locate_atom_body_matching recognises '[^N]: [id:ATOM-...]' as a lesson marker (span = marker line only; a sibling footnote closes the span); update-mem-atom reads stdin only when the body span is non-empty and preserves the '[^N]: [...]' marker shape on rebuild (footnote_block_marker parses the props). 3 new tests (span, marker parse, CLI end-to-end without stdin); memgrep 441 green. The review's 3-desc migration COMPLETED with this verb: all 3 over-cap lesson descs shortened, zero over-cap descs remain corpus-wide.
