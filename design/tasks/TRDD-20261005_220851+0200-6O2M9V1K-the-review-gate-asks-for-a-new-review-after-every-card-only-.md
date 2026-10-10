---
trdd-id: 6O2M9V1K
title: The review gate asks for a new review after every card-only commit and its reviewers cannot see commits of the same turn
column: human_review
status: tasked
created: 2026-10-05T22:08:51+0200
updated: 2026-10-10T15:31:10+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:08:51+0200
---

# The review gate asks for a new review after every card-only commit and its reviewers cannot see commits of the same turn

Goal: investigate, verify and fix the root cause. Found on 2026-10-05; not investigated beyond what is written here.

Observed about eight times in one session: after a commit that changed only cards, the stop gate demanded another adversarial review; fixing what that review found needed another commit, which re-armed the gate. Four reviews also reported that a commit 'does not exist' because a fork inherits the transcript only up to the turn that spawns it. The gate belongs to another project. To do: write up the two behaviours with examples and send them to that project's owner through the usual channel; no change is made to its code from here.

## Approval log

- 2026-10-05T22:08:51+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Write-up

2026-10-10 15:31, wave 10 card 2, no code. Both behaviours are STILL PRESENT on 2026-10-10, observed by the main session in this repository: (1) after each commit that changed only cards the stop gate demanded a review fork (the drain card TRDD-S6GX1DHN counts them per wave: 7 forks in wave 8 at 0.23 to 0.31 million tokens each, 9 in wave 7); a correction that a review asks for needs a further commit, which arms the gate again. (2) A review fork inherits the transcript up to, and not including, the response that spawns it, so a commit made in that same response is invisible to it; in wave 7 three of nine reviews reported only that the commit did not exist. WORKAROUNDS in use here, which do not need the gate changed: card-only dispositions of a wave go in one commit; the commit's content is pasted into the fork's prompt; the fork is told the commit exists. DRAFT for the gate's owner, not sent: 'The review gate demands a new adversarial review after every commit, including a commit that changes only task cards and a commit that only records the previous review's corrections, so one card can take several review rounds at 0.2 to 0.5 million tokens each. Two requests: (a) let a commit whose only content is the previous review's accepted corrections satisfy the gate without a new fork; (b) say in the gate's directive that the fork cannot see the spawning response, so the proposer must paste the commit's content.' To-do items: the write-up is done above; SENDING it is NOT done: the gate belongs to another project and posting there is outward-facing, which stays with the owner (the project that ships the agentlenspro review-gate command; its repository was not looked up).
