---
trdd-id: 23QM8H5F
title: memgrep new-mem-atom truncates a long description mid-word instead of refusing or wrapping
column: backburner
created: 2026-09-22T21:33:27+0200
updated: 2026-09-22T21:33:27+0200
current-owner: emanuelesabetta
created-by: emanuelesabetta
task-type: bugfix
min-approval-requirement: none
assignee: emanuelesabetta
mandate: true
mandated-by: none
approved: true
approval-judge: emanuelesabetta
approval-datetime: 2026-09-22T21:33:27+0200
---

# memgrep new-mem-atom truncates a long description mid-word instead of refusing or wrapping

Observed 2026-09-22 on .claude/project/memory/macos-keychain.md after the memgrep split
chore: `memgrep new-mem-atom` truncated a long `description:` mid-word instead of refusing
or wrapping it at the cap. Four descriptions were cut mid-word (e.g. "hit the iden" instead
of the full phrase); fixed by hand in commit ebe664f9.

The fix belongs in the memgrep crate (scripts/memgrep), not in the memory pages themselves:
`new-mem-atom` (and any other verb writing `description:`) must either reject a description
over the 200-char cap with an actionable error, or wrap/truncate at a word boundary --
never cut mid-word silently. Silent mid-word truncation is unfindable at write time and
corrupts the recall ranking surface (description is the only field memgrep ranks on).

## Approval log

- 2026-09-22T21:33:27+0200 — MANDATE issued by emanuelesabetta (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
