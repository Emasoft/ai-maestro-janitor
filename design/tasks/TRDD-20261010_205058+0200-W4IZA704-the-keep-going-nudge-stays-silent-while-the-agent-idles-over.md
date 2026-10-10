---
trdd-id: W4IZA704
title: The keep-going nudge stays silent while the agent idles over an open board
column: todo
status: tasked
created: 2026-10-10T20:50:58+0200
updated: 2026-10-10T20:54:17+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-10T20:50:58+0200
---

# The keep-going nudge stays silent while the agent idles over an open board

Owner, 2026-10-10 20:50, verbatim: 'why are you slacking? how many TRDDs are still not completed? you need to find a way to make the janitor nudge the agent to complete the TRDDs'. Context: the session answered two heartbeats with nothing but 'janitor heartbeat' while it waited for a 16-minute test run, with 48 todo cards on the board. THE NUDGE ALREADY EXISTS (scripts/dispatch.py, _phase_keep_going_nudge, read in full by the main session) and did not fire. MEASURED in this project's dispatch.log: 3528 keep-going decisions on record; 3079 'suppressed (user active)', 242 'board unchanged since last nudge, quiet', 115 'all agents live', 69 emitted, 12 empty board, 11 lease held by another session. So the nudge was emitted on 2 percent of its decisions and the user-presence gate accounts for 87 percent of the silence. Tonight, 14 consecutive fires from 19:40 to 20:45 were all suppressed as 'user active'. THREE CANDIDATE DEFECTS, none verified yet: (1) the gate asks whether the USER is idle, not whether the AGENT is idle; an owner who is present and watching an idle agent is the case of tonight, and the gate treats presence as proof of progress. (2) Between 19:40 and 20:10 the 'user active N s ago' figure went 445, 65, 365, 214, 155, 107 while no owner message is on record in that window, so something other than a human prompt may be resetting the presence stamp (a heartbeat prompt, a task notification, a hook); to verify in the code that writes the stamp. (3) With no pending agent, an unchanged board signature silences the nudge after its first emission (242 times), although the docstring says re-firing on every due fire is the point. TO DECIDE on facts: what 'the agent is idle' can be read from (the transcript's last entry and its age, a turn in progress, running background shells or agents), and the wording of the nudge: it should name the next workable card from trddgrep next, not only 'continue your pending task'. CONSTRAINTS: a nudge must not start work in a project whose owner gave no mandate (the owner's rule that the working directory is not an instruction): gate on an open mandate card such as a board drain, or on work in flight; never print the same line every 5 minutes to an owner who is reading (TRDD-0NWG4LKJ, warn once); the thresholds and the measured 2026-09-15 churn (4 identical cues in 25 minutes while agents were alive) must not come back. Verify: a test per candidate defect that fails first; then dispatch.log shows an emitted nudge on a fire where the owner prompted less than 600 s earlier and the agent had been idle.

## Approval log

- 2026-10-10T20:50:58+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Findings

2026-10-10 20:54. Candidate (2) READ IN CODE: scripts/hooks/on-prompt-submit.py stamps user presence for every prompt except one whose first five lines start with [janitor-. A background-task notification, a stop-hook feedback prompt and the machine-typed /janitor-resume (which begins with a command-message tag) carry no such line, so each would count as the owner typing; NOT yet proven by a test, and the one live reading taken (20:50:02) matched a real owner message. Candidate (1), from the advisor and agreed: a cron only fires when the session is idle, so every heartbeat already proves the main agent is idle at that instant; the 600 s owner mute measures the owner instead. Tonight's 14 suppressed fires ran while a background shell (a test run), which the pending-agent count cannot see, was the only work in flight. PROPOSED DESIGN, to put in one worker prompt and one review: shorten the owner mute to a debounce of at most 120 s after a GENUINE human prompt; make the presence hook ignore task notifications, hook feedback and command-message prompts typed by the janitor; keep the agents-alive suppression (regression test for the 2026-09-15 churn case); make the unchanged-board case a bounded repeat (every Nth fire) and not a mute; make the nudge name the top card of trddgrep next. Gate on a mandate or work in flight, as the body says.
