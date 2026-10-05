---
trdd-id: 0NWG4LKJ
title: The janitor collects the anomalies it sees and opens a card for each one by itself
column: design
status: tasked
created: 2026-10-05T22:14:00+0200
updated: 2026-10-05T22:14:29+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T22:14:00+0200
---

# The janitor collects the anomalies it sees and opens a card for each one by itself

Owner directive, 2026-10-05, verbatim: "do you realize that this exact procedure, of collecting the anomalies and open a TRDD for each one with investigate-verify-fix goal, is the thing that the janitor should do by itself?"

Context: on 2026-10-05 a session found more than fifty anomalies by hand (false rotator verdicts, a process larger than the machine's memory, a task that overran its budget many times over, an unexplained tick failure, leftover files, a worker looping on a failing command) and opened one card for each only when the owner asked, twice. Most of them were already visible in the janitor's own logs and state as single lines nobody collected.

What exists today, as seen in that session and NOT yet read in the code: detectors write advisory findings to a ledger and print some as drift lines; some classes of finding become support tickets that a repair agent works; nothing was seen that turns a finding into a card on the board, and lines such as 'exited 1', 'evaluation failed', 'budget exceeded', 'timed out' in the daemon's log were not seen to become findings at all.

Wanted: the janitor itself (1) harvests anomalies from its own logs, state and detectors, including the ones that are only a log line today; (2) deduplicates them against open cards and against each other; (3) opens one card per anomaly with the goal to investigate, verify and fix the root cause, stating what was observed and what is not yet verified, with no private data in a project card; (4) reports only the count to the conversation.

To settle in design before any code: which scope a card gets when the anomaly is about one machine; a cap so a noisy detector cannot flood the board (the hand-made batch of that day already holds duplicates and overstated wording, as its reviews showed); who may open a card unattended; how this relates to the existing findings ledger and ticket path, which must be read first. The fifty-odd cards opened by hand that day are the worked example and the first test set.

## Approval log

- 2026-10-05T22:14:00+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Corrections

2026-10-05 (review): the owner's sentence is a question about a design gap, not an order to build; this card sits in the design column until the owner confirms. Measured that day: 54 cards opened by hand, not 'more than fifty anomalies' (several are duplicates, one is a to-do list). 'Most were visible in the janitor's own logs' was not counted: some were; others came from reading code, from review rounds, from other sessions' transcripts and from the system's memory reports, which the janitor does not hold. The procedure the owner named includes the adversarial review and correction rounds: about a third of the hand-made cards needed corrections, so an automatic version without that step would file overstated cards at scale. Most of the anomalies needed a model's judgment across several sources, not a search of a log. The existing ticket and repair-agent path and the drift detector were not read and may already cover part of this; they are the first thing to read and the likely vehicle. Lesson for the session itself: it did not see this gap until the owner pointed at it.
