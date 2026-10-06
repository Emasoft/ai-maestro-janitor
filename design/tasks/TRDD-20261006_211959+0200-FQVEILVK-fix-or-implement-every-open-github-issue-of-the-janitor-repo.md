---
trdd-id: FQVEILVK
title: Fix or implement every open GitHub issue of the janitor repo (30 issues, 2026-10-06)
column: dev
status: tasked
created: 2026-10-06T21:19:59+0200
updated: 2026-10-06T23:11:25+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-06T21:19:59+0200
---

# Fix or implement every open GitHub issue of the janitor repo (30 issues, 2026-10-06)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-06

All sweep fixes are on main through afc8e000; the full suite is green (18,047 passed). Nothing is released yet.
Issues closed on GitHub so far: 14 of the 30 (#306 #307 #310 #311 #312 #314 #316 #317 #318 #319 #320 #325 #327 #330, from the issue map below intersected with the closed list of 2026-10-06). The other 16 (#309 #313 #315 #321 #322 #323 #324 #326 #328 #329 #331 #332 #333 #334 #335 #336) wait for the release. #332 (owner card TRDD-6ESS2MGE) stays open after the release as the board-hygiene tracker.
Process note: two workers broke the no-scripted-edit brief by rewriting tests/test_issue_catalog.py with python scripts; the diffs were read and accepted.
NEXT ACTION: publish via scripts/publish.py; then close the released issues citing the main SHAs and the release tag; then work the board-hygiene items per card (never by script).

Owner directive, verbatim, 2026-10-06: 'verify and fix/implement all of them. all issues, no exceptions.' (the open issues of Emasoft/ai-maestro-janitor: 306, 307, 309-336, 30 in all). Owner ruling on the edit tool, verbatim answer to the question how to edit code while fastedit is frozen: 'Allow plain edits for this job'. Method: a read-only triage first (reports/board/*-github-issues-triage.md), then per issue: verify the symptom in current code, fix with a failing test first, full crate and Python suites, an adversarial review, a commit naming the issue, then a closing comment on the issue that names the commit and the release. Issues already fixed and released are closed with that evidence. Each issue gets its own card or an existing owner card; this card tracks the set.

## Approval log

- 2026-10-06T21:19:59+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## STATE

2026-10-06 issue to card map: #306=V3BQT7QE (reopened symptom owned by RAEGS1D5), #307=O92E8RM7, #309=KAXQH0J5, #310=M0JACXNW, #311=ECHE9N4I, #312=1T9034NC, #313=K2PEAYHR, #314=LP0ZCOIS, #315=V13M5YY1, #316=IRBTX41Q, #317=0LNV06LT, #318=2AVXCT2L, #319=SFWYVPGC, #320=WFYJX2XU, #321=TMZRFMZL, #322=8COB99QQ, #323=7V9DQZ9D, #324=4TECXZXP, #325=M6QJ3IUN, #326=2OJG0L0E, #327=EMMXG7GW, #328=Q23COADS, #329=C9O4DJ7T, #330=7KI11RH7, #331=ZNCH1MUT, #332=6ESS2MGE, #333=KKDYNB56, #334=9Z2MGBA5, #335=4LXEFG9I, #336=0YVUX6RE.
fastedit itself stays frozen; the plain-edit exception covers this sweep only.
2026-10-06: all 7 groups merged on main (through 6f45acf8, cards 4f29d825); full suite green; follow-ups for #326/#331/#336 in progress; #321 awaits owner decision; 6f45acf8 is shared by #315/#322/#331 (one test+spec commit).
Release tracking: this card owns the sweep release; after the follow-ups for #326/#331/#336 merge and the owner rules on #321, publish via scripts/publish.py, then close each issue and move its card to complete with an acceptance checklist.
