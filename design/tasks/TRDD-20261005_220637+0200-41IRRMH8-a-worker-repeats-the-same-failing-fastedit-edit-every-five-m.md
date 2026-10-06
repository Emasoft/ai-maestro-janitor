---
trdd-id: 41IRRMH8
title: A worker repeats the same failing fastedit edit every five minutes for hours and nothing stops it
column: todo
status: tasked
created: 2026-10-05T22:06:37+0200
updated: 2026-10-06T16:38:32+0200
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

## Corrections

2026-10-05 (review): the runs were seen at 18:27 and then at about five-minute intervals from 20:40 to 21:40; nothing was searched between 18:27 and 20:40. That each run loads the local model is NOT established (output and duration were not read; a refused or anchored edit may load nothing). The worker is a subagent; that it ran in the background is not established. In this repository the only deliverable is the decision on a detector; the loop itself belongs to the other project.
2026-10-06: related ruling for this project's own workers: after a fastedit refusal the owner refused any plain-edit fallback (verbatim: "the answer is no. if the trddgrep tool is not flexible enough to make the changes you need, open an issue on Emasoft/ai-maestro"). A worker records the refused edit and stops; it does not re-run the same edit, which is the loop this card describes.
2026-10-06 CORRECTION: the line above beginning "2026-10-06: related ruling" binds nothing. The owner's quoted answer was to one question (a plain edit for TRDD-ZYX8B2RA) and does not mention fastedit or workers; the no-fallback rule comes from the standing rule code-tools-tldr-fastedit; "does not re-run the same edit" was the main agent's own idea and is outside this card's deliverable, which is a detector decision.
