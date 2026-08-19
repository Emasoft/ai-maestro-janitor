---
trdd-id: PGN5XSHA
title: A deliberately killed subagent stays in the pending manifest and the resume directive keeps telling the session to resume it
column: dev
created: 2026-08-16T06:41:27+0200
updated: 2026-08-19T01:05:00+0200
current-owner: janitor-session
task-type: bugfix
project-id: ai-maestro-janitor
approval-tier: 0
relevant-rules: []
npt: []
eht: []
blocked-by: []
implementation-commits: []
---

# A killed subagent stays `pending`, and the resume directive keeps saying "resume it"

## ⏵ STATE — 2026-08-19: fix DECIDED (Fable), in `dev`, delegated to a lean-worker. Read before implementing.

The fix was left "not decided" + carried an advisor open-question. Decided this session
(investigated the mechanism first-hand):

**Load-bearing finding — the janitor has NO TaskStop hook.** `on-subagent-stop.py` (SubagentStop)
evicts on normal COMPLETION (it receives `agent_id` → `pending_agents.remove`), but a `TaskStop`
KILL is not a janitor hook point at all — so the manifest CANNOT auto-detect a deliberate stop.
Any fix keyed on "detect the kill" is impossible. Therefore the fix is TWO parts, and the
**directive-honesty part is the one that actually prevents the measured harm** (the mark_stopped
part only helps when a caller happens to know):

1. **`pending_agents.mark_stopped(agent_id)`** — mirrors `remove()` but SETS `stopped: True` on the
   entry instead of dropping it (kept for audit, box 1). **LANDMINE:** `_normalize()` REBUILDS each
   entry from a FIXED key set and silently drops any field not named there — so `stopped` MUST be
   added to the rebuilt dict (`"stopped": bool(entry.get("stopped", False))`) or it vanishes on the
   first load. This is the same trap the `transcript`/`agentDir` comments already warn about.
2. **count + directive SKIP stopped** — `_pending_agent_count` (dispatch.py) →
   `len([e for e in pending() if not e.get("stopped")])`; `directive_lines()` skips `stopped` entries.
3. **Directive made SAFE-BY-DEFAULT (the real fix)** — since a kill can't be auto-marked, the resume
   directive must not blindly COMMAND a resume of any listed agent. Change its wording from the
   imperative "resume each via SendMessage" to advisory: name the count, then "before
   SendMessage-resuming any, confirm it is still wanted — one may be an agent you deliberately
   stopped, and a resume re-enters it from its transcript." This makes blind-following safe whether
   or not `mark_stopped` was called.
4. **Correct the two docstrings** that assert the harmlessness this card disproves:
   `on-subagent-stop.py` ("an over-listed agent … is harmless") and `_pending_agent_count`
   ("a WEEK-old corpse is still worth naming") — both true only for a DIED agent, not a stopped one.
5. **Test** — `mark_stopped` an agent, assert `directive_lines()` does not name it and the count
   excludes it; and that a DIED (un-marked) agent is still named (recovery preserved).

Answer to the advisor open-question (resuming a deliberately-stopped agent — ever wanted?): rarely,
so do NOT hard-drop it — keep it in `pending()` for audit and let the human choose via the honest
directive; never auto-resume it. Delegated to lean-worker with this exact spec 2026-08-19.

## Measured tonight, first-hand

This session spawned three subagents:

| agent | how it ended | still in `pending-agents.json`? |
|---|---|---|
| the G4BCRUP7 sweep worker | completed normally | **NO** — removed |
| advisor #1 (wedged 34 min) | **killed** via `TaskStop` | **YES** |
| advisor #2 | running | yes (correct) |

So `on-subagent-stop.py` **is** receiving `agent_id` on this build — a normal completion evicted
its entry. The discriminator is not "the documented schema has no id", which is the reason the
hook's own docstring gives for tolerating over-listing. It is that **a kill does not produce the
same removal a completion does.**

The consequence is not cosmetic. `_pending_agent_count` (`dispatch.py:965`) counts ALL entries and
does not nudge, so the heartbeat's resume line reported *"2 background agent(s) pending — resume
each via SendMessage"* while one of the two was a corpse I had just killed **because it was
wedged**. `SendMessage` to a stopped agent resumes it from its transcript — so following the
directive re-enters the exact wedge the kill escaped, once per fire.

## The design assumption that is wrong, stated precisely

`_pending_agent_count`'s docstring: *"an agent that died must still be named for a
SendMessage-resume … a WEEK-old corpse is still worth naming"*. `on-subagent-stop.py`'s: *"an
over-listed agent in a resume directive is harmless (a ping to a finished agent just restates its
result)."*

Both are defensible for an agent that **DIED** — resuming recovers stranded work. Neither holds for
an agent the session **deliberately STOPPED**. The manifest cannot tell those two apart, and they
want opposite treatment:

| ending | resume is | today |
|---|---|---|
| crashed / rate-limited / OOM | **recovery** — the point of the manifest | listed ✓ |
| deliberately `TaskStop`ped | **undoing a decision the session just made** | listed ✗ |

## Exposure is BOUNDED — do not overstate it

Corrected while writing this, because the first read was worse than the truth: eviction exists —
`MAX_NUDGES` (3 unheeded listings) and `UNNUDGED_MAX_AGE_S` (1 h for an entry no path ever listed),
under a `MAX_AGE_S` 7-day backstop. So a killed agent is not named forever. But the count path does
not nudge, so a killed entry can be COUNTED every fire for up to an hour — ~12 fires at `*/5` —
each one a directive telling the session to resume a corpse it stopped on purpose.

## Proposed fix (design, not decided)

Distinguish *stopped* from *died* at the point of the kill, which is the only place the intent
exists. Sketch: a `pending_agents.mark_stopped(agent_id)` the session calls when it `TaskStop`s an
agent (or an evicting `remove`), so the entry leaves the manifest with the same finality a normal
completion gets. Failing that, record `stopped: true` and have `directive_lines()`/the count skip
those while `pending()` keeps them for audit.

Open question for the advisor: is there any case where resuming a DELIBERATELY stopped agent is
what the operator wants? If yes, the directive must at least SAY the agent was stopped, so the
reader is choosing rather than obeying.

## Acceptance criteria

- [ ] A stopped-vs-died distinction exists in the manifest, with the kill site recording it
- [ ] The resume directive and `_pending_agent_count` no longer name a deliberately stopped agent
      (or name it as stopped, if the advisor says resuming one is legitimate)
- [ ] A test that kills an agent, then asserts the directive does not instruct a resume of it
- [ ] The two docstrings above are corrected — they currently assert the harmlessness this card
      disproves, and a wrong comment outlives a wrong line of code
- [ ] `uv run pytest -q`, `ruff check scripts tests`, `mypy scripts/ --ignore-missing-imports` clean

## Explicitly NOT in scope

Removing the corpse-naming behaviour for agents that genuinely died. That is the manifest working
as designed and it is what makes an unattended night survivable.
