---
trdd-id: 6ESS2MGE
title: Advisory findings reach the agent or the owner instead of dying in the ledger
column: design
created: 2026-09-24T08:11:58+0200
updated: 2026-10-06T23:47:34+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: feature
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-24T08:11:58+0200
---

# Advisory findings reach the agent or the owner instead of dying in the ledger

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-06

GitHub #332 (weekly audit drift) is owned by this card and STAYS OPEN after the sweep release as the board-hygiene tracker, never closed by the release. Open items, to be worked per card and never by script: trdd-drift reports about 60 idle cards, trdd-reminder has 43 active, trdd-state-reconciliation has 80 candidates of which 35 are closeable.
NEXT ACTION: after the sweep release ships, work the board-hygiene items card by card; close #332 only when each class is fixed or shown to need no action. The routing design in the body is still undecided (column design).
- 2026-10-07: the reconciliation detector now records closeable candidates as one-time TRDD-CLOSEABLE findings-ledger notes (TRDD-8BNV75TV); nothing routes those notes to the agent or owner yet, which is this card's routing design to decide.

dispatch.py's _ADVISORY_DETECTORS (trdd-reminder, dirty-tree, gitignore-coverage, github-issues-watch, gh-reply-watch, and others) are quiet-filtered to the findings ledger, so new GitHub issues #306 and #307 (2026-09-22/23), 29 dirty-tree hits and 15 trdd-reminder hits in one week (ledger counts, 2026-09-17 to 2026-09-24) never reached anyone. The 2026-08-12 owner rule ("a fire prints janitor heartbeat, and ONLY adds to it when something genuinely needs the human") and the 2026-09-24 directive (TRDD-WZKFSQ2N) now conflict. OWNER DECISION needed on routing. TRDD-ADIGRD0T is the agent-facing half.
v3.8.0 shipped the weekly re-report fix (abee9ac5, 14db6c88, afc8e000); remaining audit items tracked on #332

## Approval log

- 2026-09-24T08:11:58+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
OWNER DECISION 2026-09-27 (verbatim, condensed for the routing rule): 'advisories must reach the agent if they need the agent to act. if they can be solved opening a ticket for a subconscious agent acting lazily in background to fix the issue, the agent does not need to be informed. the less we distract the main claude from its tasks the better. make the issues and the chores invisible to it when possible. and be sure to not open tickets for issues that are relative to other projects or claude instances. bugs in memgrep for example are an issue for the janitor plugin, so they must be opened as new issues on the janitor plugin github repo. the same for the janitor daemon or other janitor related things, the cpv plugin, or any other plugin or component. to each its own issue on its own repo.' Routing rule: (1) agent-facing ONLY when the agent must act; (2) subconscious-fixable -> background ticket, invisible to the main agent; (3) component-owned -> issue on that component's own repo (memgrep/janitor -> ai-maestro-janitor; cpv -> its repo), never to an unrelated instance.
2026-10-06 cross-reference: GitHub #332 (weekly audit drift) is owned by this card; the duplicate owner TRDD-Y8DB5F0M was superseded by it.
2026-10-06 sweep finding (audits group, reports/issue-sweep/20261006_212638+0200-audits-crossrepo.md): of #332's drift items, the oversized memory page is already fixed; the rest are advisory detector findings with no code defect (memorize nudge, cross-card blind spot 688 pairs, reconciliation 80 candidates, reminders, dead symbols named in the STATE blocks of TRDD-AR9IUGIJ, TRDD-BMITQ2MN and TRDD-5MOX0FPO); #332 closes when this card's design lands or when each class is shown to need no action.
