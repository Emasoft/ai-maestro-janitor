---
trdd-id: QNMBH3ES
title: AICTX-003 dedupe key embeds the line number so an unrelated edit above the match re-mints a byte-identical proposal
column: todo
created: 2026-09-03T09:23:01+0200
updated: 2026-09-03T09:23:01+0200
current-owner: janitor-main-session
task-type: bugfix
priority: normal
severity: medium
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
labels: [detector, agent-context-integrity, issue-catalog, dedupe]
relevant-rules: []
blocked-by: []
npt: []
eht: []
implementation-commits: []
external-refs: [janitor#291]
created-by: issue triage 2026-09-03
---

# AICTX-003 dedupe key is line-number-unstable

## Measured (janitor#291, re-verified 2026-09-03)

`scripts/detectors/agent-context-integrity.py:601` raises the finding with
`where=f"{rel}:{f.line}"`, and `scripts/lib/issue_catalog.py::_finding_key` (~line 578) folds
`where` into the dedupe key. Any edit ABOVE the flagged span shifts `f.line`, the key changes,
and the catalog mints a second proposal whose content is byte-identical to the first. The
suppressive `refused` disposition shipped for janitor#110 is defeated while the key itself moves.

## Fix

Key AICTX-003 on `{rel}:{rule_id}:{sha1(matched_span)[:12]}` — the file, the rule, and a hash of
the matched text — never the line. Keep the line in `evidence`/the human message so the reader
can still jump to it. `_finding_key` needs no change if `where` stops carrying the line; verify
by reading `_finding_key`'s docstring (it warns that a key computed "even slightly differently"
never retracts) and add the migration note there.

## Acceptance

- [ ] Test: the same match at line 40 and, after inserting 3 lines above it, at line 43 yields
      ONE catalog entry (second raise is a no-op / same key).
- [ ] Test: two different matched spans in the same file under the same rule yield TWO keys.
- [ ] Existing open AICTX-003 proposals keyed by line are retracted or re-keyed on the next
      detector pass (state the mechanism; no silent duplicates left behind).

## Approval log

## Notes and lessons learned
