---
trdd-id: 41IRRMH8
title: A worker repeats the same failing fastedit edit every five minutes for hours and nothing stops it
column: backburner
status: tasked
created: 2026-10-05T22:06:37+0200
updated: 2026-10-10T14:46:32+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:06:37+0200
---

# A worker repeats the same failing fastedit edit every five minutes for hours and nothing stops it

Goal: investigate, verify and fix the root cause. Observed 2026-10-05 in another project's session: a background worker ran 'fastedit edit' on the same temporary file at about five-minute intervals from at least 18:27 to 21:40, each run loading the local model. It was not shown to be the cause of the hang, but it adds a model-sized process to the host on every round and nothing noticed the loop.

To do: establish what drives the repetition (a cron, a retry loop in the worker's prompt, or a resumed agent); check whether the janitor's stalled-worker or peer-freeze detectors should have seen it; decide whether the janitor reports a worker that repeats an identical failing command, and to whom. The session belongs to another project: its Claude is told through the usual channel, its tree is not edited from here.

## Approval log

- 2026-10-05T22:06:37+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-10T14:44:28+0200 — column → backburner. decision 2026-10-10: no detector on one unexplained instance; pull condition on the card

## Corrections

2026-10-05 (review): the runs were seen at 18:27 and then at about five-minute intervals from 20:40 to 21:40; nothing was searched between 18:27 and 20:40. That each run loads the local model is NOT established (output and duration were not read; a refused or anchored edit may load nothing). The worker is a subagent; that it ran in the background is not established. In this repository the only deliverable is the decision on a detector; the loop itself belongs to the other project.
2026-10-06: related ruling for this project's own workers: after a fastedit refusal the owner refused any plain-edit fallback (verbatim: "the answer is no. if the trddgrep tool is not flexible enough to make the changes you need, open an issue on Emasoft/ai-maestro"). A worker records the refused edit and stops; it does not re-run the same edit, which is the loop this card describes.
2026-10-06 CORRECTION: the line above beginning "2026-10-06: related ruling" binds nothing. The owner's quoted answer was to one question (a plain edit for TRDD-ZYX8B2RA) and does not mention fastedit or workers; the no-fallback rule comes from the standing rule code-tools-tldr-fastedit; "does not re-run the same edit" was the main agent's own idea and is outside this card's deliverable, which is a detector decision.

## STATE

2026-10-10 15:30 (TRDD-S6GX1DHN wave 8 card 4). DECISION, by the main session under the owner's mandate of 2026-10-09: NO detector is built now; the card goes to backburner. READ FIRST: scripts/detectors holds no detector for a repeated identical command; peer-freeze-recovery recovers frozen peer sessions, subagent-report nudges on unreferenced report files, subagent-scope-drift checks the tracking of agent files, and the PreToolUse token-budget hook watches a turn's tokens. None of them sees a worker repeating one failing command, so nothing 'should have seen it'. WHY NOT BUILD: one observed instance, in another project; what drove the repetition (a cron, a retry loop in a prompt, a resumed agent) was never established and the transcript was not read; that each run loaded the model is not established either (see Corrections). A detector designed from one unexplained case would be designed on an assumption. The harm the card feared, a model-sized process on every round, is now watched by the process-size watch (alert only, live since v3.7.1; its limits are on TRDD-DKID2PYP). CANDIDATE DESIGN if pulled, not evaluated: count identical failing Bash commands per session in a PostToolUse hook and nudge that session's own agent after N repeats; it reads nothing of another project. PULL CONDITION: a second observed instance of a worker repeating an identical failing command, or the process-size watch logging two or more detections of the same command line within one hour. NOT DONE: the other project's Claude was not told (the card's 'usual channel'); the incident is five days old and its session is gone.
2026-10-10 15:40 CORRECTIONS from the review of 9bb39137. (1) 'None of them sees a worker repeating one failing command' rests on FOUR files read (the heads of peer-freeze-recovery, subagent-report and subagent-scope-drift, and a grep of the token-budget hook); the detector folder was listed by a name filter and its other detectors were not read. (2) The card's first To-do item, what drove the repetition, was NOT answered: the other session's transcript was not looked for. That was a choice, and it is also the gap the decision leans on; reading that transcript, if it still exists, is the first step when this card is pulled. (3) The PULL CONDITION as written is not observable: nothing watches for a second instance, and the process-size watch's log line carries the program and script name without arguments, so 'the same command line twice in an hour' cannot be read from it. Honest form: this card is pulled when an agent or the owner reports a second instance, or when TRDD-DKID2PYP's next step (a watch log line that can classify a detection) makes repeats readable.
