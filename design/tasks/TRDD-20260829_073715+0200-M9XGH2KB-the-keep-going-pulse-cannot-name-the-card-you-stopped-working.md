---
trdd-id: M9XGH2KB
title: The keep-going pulse cannot name the card you stopped working
column: backburner
blocked-by: []
created: 2026-08-29T07:37:15+0200
updated: 2026-08-29T07:37:15+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 4
severity: MEDIUM
effort: S
min-approval-requirement: none
task-type: feature
labels: [heartbeat, kanban, continuity]
release-via: publish
test-requirements: [unit]
---

# TRDD-M9XGH2KB — The keep-going pulse cannot name the card you stopped working

## The incident that produced this card

2026-08-29, owner: *"ironically, the janitor should be responsible to nudge the agent to continue
when it has pending TRDDs, but you are not getting nudged at all.. why??"*

They were right, and the reason is structural rather than a misconfiguration. The session had
finished TRDD-ULEGRT01, left **TRDD-VJL1YTCG sitting in `column: dev`**, and then answered ~30
consecutive heartbeats with "nothing pending" — each time truthfully, as far as anything the
janitor told it.

## Why the janitor could not say otherwise

**`dispatch.py::_phase_resume`'s keep-going pulse builds its message from exactly two sources**
(measured at `dispatch.py:2510-2576`): a `resume-directive.txt` target, and the pending
background-agent count. **Nothing reads the kanban board.**

`resume-directive.txt` is written only by the CONTINUITY triggers — `compact_trigger.py`,
`clear_trigger.py`, `reload_trigger.py`, `reload_skills_trigger.py`, `hooks/post-compact-resume.py`.
It is a mechanism for surviving a `/clear`, not a work queue. On a session that never compacted, the
file does not exist (verified absent on this host at the time).

With no directive file and no pending agents, the pulse falls through to its generic branch —
whose text is *"if the work is genuinely finished, or you are blocked on a human decision, say so
briefly and stop"*. **That branch actively ratifies stopping.** It is the correct text for a
finished session and exactly wrong for one with a card in `dev`.

**And the one board-aware detector cannot cover the gap either.** `trdd-drift` fires at
`CLAUDE_PLUGIN_OPTION_TRDD_STALENESS_DAYS`, default **14 days** untouched
(`detectors/trdd-drift.py:145,303`), and is in `_ADVISORY_DETECTORS`, so it routes to the findings
ledger rather than stdout. VJL1YTCG had been touched two days earlier. It was ~12 days from being
visible at all, and even then would have landed somewhere nobody was looking.

So the machinery is built for **abandoned** cards, and the failure mode here is **interrupted**
ones — a card stopped mid-session, minutes ago, by the very agent being nudged.

## The inversion, which is the point

| line | can the reader act on it? | what the janitor did |
|---|---|---|
| `memgrep lint: 1053 finding(s), 1009 at or above ERROR` | **no** — librarian work by owner directive | **promoted past quiet mode, every fire, for hours** |
| "TRDD-VJL1YTCG sits in `dev`, untouched since you stopped" | **yes** — the reader owns it | **never emitted, by construction** |

The noisy half was fixed in TRDD-VJL1YTCG Part C (`_OTHER_ACTOR_DETECTORS`). This card is the
silent half. They are worth reading together: the heartbeat's attention budget was being spent
almost exactly backwards.

## Proposed shape (not yet decided — this is `backburner` on purpose)

Add a THIRD source to the keep-going pulse's `bits`: the session's own in-flight board state.
Sketch, to be argued with rather than implemented as written:

- When the pulse would otherwise emit the generic "say so and stop" text, first ask whether any
  card is in a WORK column (`dev`/`testing`/`ai_review`) — the columns that ASSERT someone is
  working right now (see `the-kanban-is-a-pipeline-that-must-drain.md`). If so, name it:
  `TRDD-<id8> is in dev — resume it or move it out of the work column`.
- **Threshold must be much tighter than trdd-drift's 14 days** — this is about a card stopped
  minutes ago, so hours at most, possibly "since this session last touched it".
- It must NOT duplicate `trdd-drift`: that detector answers "which cards has the PROJECT
  abandoned", this answers "which card did THIS SESSION stop working". Different question, different
  cadence, different consumer. Resist folding them together.

## The trap to design around

**Do not make this a nag.** The generic branch's current wording exists because issue #74 showed
sessions reaching for an off-switch while merely BLOCKED ON A HUMAN — the pulse must survive that.
A board-aware nudge that fires when the agent is legitimately waiting on the owner would recreate
exactly that pressure, and the fix would be to silence the pulse, which is worse than the disease.
So: a card in `dev` with a non-empty `blocked-by:`, or one whose card says it is awaiting a human,
must NOT produce a nudge.

## Acceptance

- [ ] The pulse names a card the session left in a WORK column, within hours not days.
- [ ] It stays silent for a card that is legitimately blocked (`blocked-by:` non-empty / awaiting
      human), so the issue-#74 pressure is not recreated.
- [ ] It does not duplicate or replace `trdd-drift` — both keep their distinct question.
- [ ] A test that would have caught the original incident: a card in `dev`, untouched for one hour,
      produces a nudge naming it.

## Notes and lessons learned

- 2026-08-29 — **A guard built for the abandoned case is not a guard for the interrupted case.**
  `trdd-drift` at 14 days is correct for "the project forgot this card" and structurally incapable
  of catching "the agent stopped 40 minutes ago", which is the far more common and far more
  recoverable failure. When a safety net has a threshold, ask which failure the threshold was
  chosen for — and whether the one you actually keep hitting is a different one wearing the same
  name.
- 2026-08-29 — **The most dangerous message a supervisor can send is one that ratifies stopping.**
  The keep-going pulse's fallback text is well-argued and correct for a finished session; the bug
  is that it is also what an UNfinished session receives, because the pulse cannot tell the two
  apart. A default that is right in one state and actively wrong in another needs to know which
  state it is in, not better wording.
