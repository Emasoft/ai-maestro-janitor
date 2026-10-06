---
trdd-id: ZNCH1MUT
title: memgrep write verbs cannot correct a lesson by id, lack a page description verb and have an undocumented stdin contract
column: testing
status: tasked
created: 2026-10-06T21:26:08+0200
updated: 2026-10-06T23:10:08+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:26:08+0200
implementation-commits: [6eabe6b7, 15344f01, 6f45acf8, a0506578, 8586f043]
---

# memgrep write verbs cannot correct a lesson by id, lack a page description verb and have an undocumented stdin contract

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-06

landed on main as 6eabe6b7,15344f01,6f45acf8,a0506578,8586f043; ships in the next release; issue stays open until then. Follow-ups for #331 landed on main (a0506578 memgrep crate 0.1.0 to 0.2.0; 8586f043 repair skill page-description rewrite must prove no recall loss, a skill instruction only with no automated test).
NEXT ACTION: close the GitHub issue citing the main SHAs once the next publish.py release ships.
FOLLOW-UP LOCATION: landed on main as 6eabe6b7,15344f01,6f45acf8,a0506578,8586f043 (the follow-up worktree is merged).
COLUMN MEANING: testing here means merged on main and full suite green (18,047 passed at afc8e000), awaiting the sweep release tracked on TRDD-FQVEILVK; nobody is testing it. The #331 repair-skill rule (page-description rewrite must prove no recall loss) is a skill instruction only, with no automated test. `complete` needs an acceptance checklist: add it and move to complete when that release ships.

Source: GitHub issue Emasoft/ai-maestro-janitor#331 (opened 2026-10-05). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: Four gaps share one cause, the write verb contract. A lesson cannot be superseded under its own id, no verb sets a page description, the stdin behaviour is undocumented, and a repair shrinks the recall surface. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:26:08+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.




