---
trdd-id: 0YVUX6RE
title: MEMCORP-001 catalog text does not match what the detector files under it and ticket wording is not enforced
column: testing
status: tasked
created: 2026-10-06T21:26:12+0200
updated: 2026-10-06T23:10:25+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:26:12+0200
implementation-commits: [3b568247, 8f5a687b, 522f2d0c, fc73c8d2]
---

# MEMCORP-001 catalog text does not match what the detector files under it and ticket wording is not enforced

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-06

landed on main as 3b568247,8f5a687b,522f2d0c,fc73c8d2; ships in the next release; issue stays open until then. Follow-ups for #336 landed on main (8f5a687b, 522f2d0c, fc73c8d2): an incomplete ticket opens with a plain-bullet "Incomplete:" list of the unmet rules. Ticket wording is FLAGGED, NOT ENFORCED: this is option B, chosen under the owner's standing decide-and-proceed ruling and vetoable by the owner.
NEXT ACTION: close the GitHub issue citing the main SHAs once the next publish.py release ships.
FOLLOW-UP LOCATION: landed on main as 3b568247,8f5a687b,522f2d0c,fc73c8d2 (the follow-up worktree is merged).
COLUMN MEANING: testing here means merged on main and full suite green (18,047 passed at afc8e000), awaiting the sweep release tracked on TRDD-FQVEILVK; nobody is testing it. `complete` needs an acceptance checklist: add it and move to complete when that release ships.

Source: GitHub issue Emasoft/ai-maestro-janitor#336 (opened 2026-10-06). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: The catalog entry describes link and structural damage, but the detector files every error severity lint finding under that code, including a merely short description. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:26:12+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.




