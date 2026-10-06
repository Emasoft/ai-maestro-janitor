---
trdd-id: 2OJG0L0E
title: Memory maintenance problems split re-dispatched forever, weekly verbatim re-arm, lint count spam, autorecall on notifications
column: testing
status: tasked
created: 2026-10-06T21:26:03+0200
updated: 2026-10-06T23:10:26+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:26:03+0200
implementation-commits: [6e95fb5e, ecb8cc7f, 9ad6b9f6, 16d832ef, 6f513d53, 65e0b9bc, 47484d08, 13c9c336, 6099a561, 26c42b4e]
---

# Memory maintenance problems split re-dispatched forever, weekly verbatim re-arm, lint count spam, autorecall on notifications

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-06

landed on main as 6e95fb5e,ecb8cc7f,9ad6b9f6,16d832ef,6f513d53,65e0b9bc,47484d08,13c9c336,6099a561,26c42b4e; ships in the next release; issue stays open until then. Follow-ups for #326 landed on main: ticketed drift suppression, content-hash aware, with one detector keyed (package-manager-policy). It takes effect only after its PROJECT proposal is approved. KNOWN LIMITS: (1) the ticketed-block-hashes store is unlocked, so concurrent fires can race (named by a ponytail comment in the code); (2) a stale digest can hide an identical reopened finding if no fire ran between the ticket close and the reopen.
NEXT ACTION: close the GitHub issue citing the main SHAs once the next publish.py release ships.
FOLLOW-UP LOCATION: landed on main as 6e95fb5e,ecb8cc7f,9ad6b9f6,16d832ef,6f513d53,65e0b9bc,47484d08,13c9c336,6099a561,26c42b4e (the follow-up worktree is merged).
COLUMN MEANING: testing here means merged on main and full suite green (18,047 passed at afc8e000), awaiting the sweep release tracked on TRDD-FQVEILVK; nobody is testing it. `complete` needs an acceptance checklist: add it and move to complete when that release ships.

Source: GitHub issue Emasoft/ai-maestro-janitor#326 (opened 2026-10-02). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: Four problems were seen. The split chore is re-dispatched about twice a day on a scope it can never act on, verbatim atoms re-arm weekly, a lint count spams the heartbeat, and auto-recall runs on task notifications. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:26:03+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.




