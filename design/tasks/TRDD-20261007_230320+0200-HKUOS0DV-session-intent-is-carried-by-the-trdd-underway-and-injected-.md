---
trdd-id: HKUOS0DV
title: Session intent is carried by the TRDD underway and injected by a SessionStart script with no agent
column: backburner
status: tasked
created: 2026-10-07T23:03:20+0200
updated: 2026-10-07T23:05:17+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T23:03:20+0200
---

# Session intent is carried by the TRDD underway and injected by a SessionStart script with no agent

## Owner directive (verbatim, 2026-10-07)

"clearly the architecture is wrong. you need a way to append to the jav compacted context a short handoff. but the only one that can do it without spending tokens is a fork of the main agent. because it has everything in cache already, and one turn will be enough to write the handoff and exits before having to invalidate the cache with the new content at the next turn. the same method used by the adversarial review hook. but this is only possible if the compaction is done live. if the compaction is done at session restart, when restarting claude, or at any api error, the main agent has no way to fork itself. it has to restart all from scratch, burning millions of tokens, invalidating the whole compaction system aim, that is to save tokens. ergo the only way is to keep the intent updated in the TRDD and kanban itself, and inject the latest trdd underway into the context, with the kanban metadata instructing the agent implicitly. a task that can be scripted and executed automatically even without executing any agent. so the start session hooks can run those scripts along with the jev compaction, instead of forking the main agent."

Context, the owner's two preceding messages in the same exchange, verbatim: "and why the hell there are two clear in a row?" and "so you are going to become an idle agent too?"

## Design (main agent, not owner text; revised after adversarial review 2026-10-07)

- Intent lives in the card being worked: its STATE block plus column and assignee, kept current during the work.
- A SessionStart script, no agent and no model turn, injects the latest card underway next to the Jev compacted context; same path after a clear, a restart or an API error. No fork of the main agent for this job (the owner ruled it out for the restart case).
- "Latest underway" is first built as: newest `updated:` among cards in dev, testing or ai_review. No per-session marker unless two sessions are measured picking each other's card.
- With no card underway: inject board counts and the workable list as data. Never name a picked next card.
- Inject the STATE block first with a size cap and a pointer to the file; show how old the STATE block is relative to the session's last activity.
- Nothing is retired by this card. The owner-messages record from issue 338 (3.8.11) stays as the carrier for work that has no card.
Provenance, 2026-10-07: "no per-session marker" and "never name a picked next card" are the reviewer's suggestions adopted by the main agent. "Nothing is retired" withdraws the main agent's own earlier proposal to retire the model-written handoff, which the owner had not asked for. The owner was told all three on 2026-10-07 and had not answered by then.

## Measure before building

1. How many resumed sessions had a work-column card whose STATE named a correct next action at clear time.
2. STATE block sizes for cards in dev and testing, to set the cap.
3. In the ai-maestro stall (issue 338), whether the session read the STATE block it was pointed at and still declined.
4. How often a session's work had no card at clear time.

## Open decision (owner)

Whether a card in a work column assigned to the agent, or a janitor handoff quoting the owner's message verbatim, counts as the assignment under the owner's global no-work-without-assignment rule. Asked several times, unanswered.
The phrase in the directive closest to an answer is "with the kanban metadata instructing the agent implicitly"; it is the main agent's reading, not an owner ruling, that this may mean a work-column card assigned to the agent is the assignment.

## Known risk

Stale STATE blocks; without enforcement the problem moves from the handoff to the card.

## Acceptance checklist

- [ ] The four measurements are recorded on this card, each with its sample size and who judged it; a measurement that could not be taken is recorded as not taken and leaves this box unticked.
- [ ] A failing test exists first for the injection script.
- [ ] Field check, clear: after one real janitor clear the new session's first reply after the janitor's own setup calls names the card id of the card underway and continues it with no typed message.
- [ ] Field check, restart: the same after one real Claude restart.
- [ ] Field check, API error: the same after one turn killed by an API error, or a recorded reason why this case could not be produced.

## Approval log

- 2026-10-07T23:03:20+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Related

TRDD-IN4493LC (issue 338, the owner-messages record this design keeps); TRDD-D7RLXAN1 (the "read this first" redesign this overlaps); TRDD-FQVEILVK (an example of a stale STATE block); TRDD-HIZ9ODVX (cost comparison).
The scratch copy reports_dev/20261007-owner-directive-intent-in-trdd.md is superseded by this card.
