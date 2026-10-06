---
trdd-id: V13M5YY1
title: Wikimem page shipped with duplicated sections and validate and lint cannot see body duplication
column: testing
status: tasked
created: 2026-10-06T21:25:47+0200
updated: 2026-10-06T22:08:20+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:25:47+0200
implementation-commits: [00e80ac2, 6f45acf8]
---

# Wikimem page shipped with duplicated sections and validate and lint cannot see body duplication

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-06

landed on main as 00e80ac2,6f45acf8; ships in the next release; issue stays open until then.
NEXT ACTION: close the GitHub issue citing the main SHAs once the next publish.py release ships.
COLUMN MEANING: testing here means merged on main and full suite green (18,020 passed at 6f45acf8), awaiting the sweep release tracked on TRDD-FQVEILVK; nobody is testing it. `complete` was refused (no acceptance checklist): add the checklist and move to complete when that release ships.

Source: GitHub issue Emasoft/ai-maestro-janitor#315 (opened 2026-09-28). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: A project wikimem page carried two full copies of two sections. Neither validate nor lint detects duplicated body sections, and a hand repair left part of the duplicate in place. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:25:47+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-06T22:08:20+0200 — column → testing by main-agent@ai-maestro-janitor.




