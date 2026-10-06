---
trdd-id: TMZRFMZL
title: One command that toggles auto-rotation on both the janitor flag and the server flag file
column: testing
status: tasked
created: 2026-10-06T21:25:55+0200
updated: 2026-10-06T23:11:13+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:25:55+0200
implementation-commits: [33525949, cb236ce6]
---

# One command that toggles auto-rotation on both the janitor flag and the server flag file

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-06

landed on main as 33525949,cb236ce6; ships in the next release; issue stays open until then.
NEXT ACTION: close the GitHub issue citing the main SHAs once the next publish.py release ships; the owner may veto the decision below before then.
DECISION (2026-10-06, taken under the owner's standing "decide yourself and proceed" ruling, owner may veto): ship the current both-sides semantics. With rotation on at both sides, both stay on and the ai-maestro server's ownership lease decides which side rotates. This is stated in the release notes.
COLUMN MEANING: testing here means merged on main and full suite green (18,047 passed at afc8e000), awaiting the sweep release tracked on TRDD-FQVEILVK; nobody is testing it. `complete` needs an acceptance checklist: add it and move to complete when that release ships.

Source: GitHub issue Emasoft/ai-maestro-janitor#321 (opened 2026-09-29). Part of the issue sweep TRDD-FQVEILVK. Symptom, in plain words: The owner wants a single janitor command that enables or disables auto-rotation on both sides at once, the janitor opt-in flag and the ai-maestro server flag file, so a half-state cannot be reached. Acceptance: the symptom is gone in a test that failed before the fix, or the issue is shown obsolete or already fixed with evidence; a closing comment on the issue names the commit and the release.

## Approval log

- 2026-10-06T21:25:55+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.




