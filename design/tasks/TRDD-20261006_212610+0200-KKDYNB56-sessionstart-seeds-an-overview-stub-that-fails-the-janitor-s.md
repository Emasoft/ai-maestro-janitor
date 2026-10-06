---
trdd-id: KKDYNB56
title: SessionStart seeds an overview stub that fails the janitor's own lint WMPAGE-004
column: testing
status: tasked
created: 2026-10-06T21:26:10+0200
updated: 2026-10-06T22:08:21+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:26:10+0200
implementation-commits: [5b96fc7f, 89769546]
---

# SessionStart seeds an overview stub that fails the janitor's own lint WMPAGE-004

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-06

landed on main as 5b96fc7f, 89769546; ships in the next release; issue stays open until then.
NEXT ACTION: close the GitHub issue citing the main SHAs once the next publish.py release ships.

Source: GitHub issue Emasoft/ai-maestro-janitor#333 (opened 2026-10-06). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: The overview page seeded at session start fails the linter at error severity as written, because its description has too few phrases, and the template is fixed so every stub fails. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:26:10+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-06T22:08:21+0200 — column → testing by main-agent@ai-maestro-janitor.
