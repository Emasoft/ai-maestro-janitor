---
trdd-id: 0NWG4LKJ
title: The janitor collects the anomalies it sees and opens a card for each one by itself
column: design
status: tasked
created: 2026-10-05T22:14:00+0200
updated: 2026-10-05T22:18:21+0200
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
2026-10-05 (review of the duplicate-merging decision above): comparing only with OPEN cards was the session's narrowing, not the owner's words; the comparison includes closed and archived cards, because a sighting of an anomaly whose card is closed means a fix did not hold. A closed card's body is frozen, so that case opens a new card linked to the old one. 'Another sighting of the same root cause' is the session's reading of 'if it is the case'. 'Integrate' means the card's statement and state are rewritten into one coherent account, not a growing list of appended sightings. The 59 cards opened by hand that day are to be deduplicated and merged themselves, not only used as a test set. A sighting private to one machine is never written into a project card.
2026-10-05 (review of the owner's 'must open a TRDD for each anomaly' decision): the owner's 'must' is an order to build, so the earlier line saying this card waits for the owner's confirmation is superseded; the card is in design because design is the work now due, and it is assigned. A cap may merge anomalies into one card; it may never drop or defer one. 'A new card, or an existing one when it is a duplicate' is the session's reconciliation of the owner's two sentences, not the owner's words. Worked example, corrected: the stuck line was printed on about eleven fires in a first episode, when no card existed yet, and on about five more in a second episode while a card about the stuck alert was open (that card covers a different cause; the card for the second cause was opened afterwards). 'Never print repeatedly' applies to every surface the janitor speaks on, not only the heartbeat line: the findings lines at session start, the background-worker count, the hourly lint count, and the desktop notification, whose present backoff (again after an hour, then daily) is itself a repeat. Coverage must be looked up in the ticket store as well as on the board; neither has been read yet. The heartbeat protocol tells a session to surface the dispatcher's output verbatim, so the suppression has to happen in the dispatcher before it prints.

## Owner decisions

2026-10-05, verbatim: "the janitor must be smart enough (maybe using jev) to detect duplicates and integrate the anomalies in the same TRDD card if it is the case." Read as a requirement of this card: before opening a card the janitor compares the new anomaly with the open cards and with the other anomalies of the same pass; when it is the same anomaly, or another sighting of the same root cause, it is added to the existing card as a dated observation instead of a new card. The owner names Jev as a possible means, not as a decision ('maybe'). To settle in design: what counts as the same anomaly (same symptom, same component, same suspected cause); that a Jev verdict is a triage lead and not proof, so a merge must stay reversible and keep each sighting's own evidence; that Jev sends text to an outside model, so what is sent must hold no private data and the project's rules must allow it; what happens when Jev is unavailable (open a separate card marked as a possible duplicate, never drop the anomaly). First test set: the 59 cards opened by hand on 2026-10-05, among which the reviews already named several duplicate pairs.
2026-10-05, verbatim: "but the janitor must open a TRDD for each anomaly detected, and never print repeatedly the warning about an anomaly already convered by a TRDD or by a janitor ticket." Two requirements. (1) Every anomaly the janitor detects ends up on a card: a new one, or an existing one when it is a duplicate; none is left as only a printed line. (2) Once an anomaly is covered by a card or by a janitor ticket, the janitor stops printing its warning again. Worked example of the day: the line 'rotator alert: account rotation is stuck' was printed on a dozen consecutive heartbeat fires, and it went on after cards for it existed. To settle in design: how a printed warning is tied to the card or ticket that covers it (a stable anomaly key written on both); whether the first sighting is still printed once, with the card id; what is printed when a covered anomaly gets worse or comes back after its card was closed; and that silence must never hide an anomaly that has no card yet.
