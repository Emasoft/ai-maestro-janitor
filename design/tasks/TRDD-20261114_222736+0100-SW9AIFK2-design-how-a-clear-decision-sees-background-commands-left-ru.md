---
trdd-id: SW9AIFK2
title: Design how a clear decision sees background commands left running by an ended subagent (issue 356)
column: design
status: tasked
created: 2026-11-14T22:27:36+0100
updated: 2026-11-15T21:44:42+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-14T22:27:36+0100
---

# Design how a clear decision sees background commands left running by an ended subagent (issue 356)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-11-14

- NEXT ACTION: DESIGN CARD, nothing to build yet. (1) Fetch the discriminating evidence named below (subagent-stop log and pending-agents history around the 19:11 incident, plus 2-3 real transcripts to sample the record shapes). (2) Consult the Fable advisor (fable-advisor:advisor; run agentlenspro model-headroom fable -q first): touches 3+ files and decides what "live work" means for every clear decision. (3) Write the chosen design into this card, get it reviewed, then move to todo.
- Status: not started. Parent work: TRDD-V8GWJVFN; GitHub issue 356. Related: archived TRDD-R3YEXX4L (a command that outlives its tool timeout keeps running unwatched), TRDD-C9CO0I7L, TRDD-Q4T4PQ4J.
2026-11-15 DEFERRED clear-chain Step 7a (scripts/hooks/on-stop-token-meter.py _maybe_clear: defer a below-ceiling clear while background launches or a handoff compose are open). Reason: it adds a transcript-tail read of up to 16 MiB to every Stop once context is past the clear point and below the ceiling, while the clear it would defer never spawns, because auto clear is off (owner, 2026-11-03). Step 8 landed in 87ff6f8a. Steps 5, 6 and 7b (clear_trigger.py, the manual lanes) are HELD as a candidate design until this card's design step is done; this supersedes the 040421c0 wording that called them planned separately. Reason: 7b adds a wait inside _agents_and_interrupt_ok, which _still_wanted (scripts/clear_trigger.py:994) runs for every chain through _run_chain_payload, started by spawn_shrink_chain from dispatch.py:3963, reload_trigger.py:154, reload_skills_trigger.py:138 and hooks/on-stop-token-meter.py:184, and by _spawn_chain from external_handoff_clear.py:597 (_fire) and clear_trigger.py:1505 in main, the CLI the manual /janitor-handoff-and-clear skill runs (skills/janitor-handoff-and-clear/SKILL.md:112); per the plan a launch whose completion notice never arrives would hold such a chain for up to 4 h, and no test drives _agents_and_interrupt_ok with an open launch. The verbatim code is in the gitignored plan reports_dev/fanout-research/20261115_213500+0100-clear-chain-plan.md, Step 7 (snippet g1_meter.txt); re-apply 7a when the owner turns auto_clear_enabled on. Correction to the 87ff6f8a body, which says a full disk loses the new log line like the others: state.log_line does not catch OSError (terminal_trigger.py:660), so on a full disk the new call raises out of inject_until_sent (terminal_trigger.py:991-1478) and aborts that inject, as the four existing log_line calls at 1244, 1283, 1290 and 1298 would; the only try blocks in that function (1087, 1103, 1144) wrap probes, not these calls.

## Problem (GitHub issue 356)

"clear deferred: 1 agent(s) live" stopped holding between 19:11:02 and 19:11:49, while the worker's real work (a background vitest or until-watcher command) still ran, and the clear was then typed (and, with F1 now in, would at least wait for an idle turn).

Verified: the keep-going log "0 pending agents" at 19:12:28 comes from dispatch._pending_agent_count (about L1844) = len(pending_agents.load_pending()), i.e. the manifest holds ZERO non-stopped entries, not merely "not live". The chain's own check clear_trigger._agents_and_interrupt_ok (about L652) uses the same manifest, so two independent checks agreed through 19:13:31: the entry was GONE from pending-agents.json, not flickering. Ways an entry disappears (scripts/lib/pending_agents.py): remove(agent_id) from on-subagent-stop.py (about L52-70, only when the SubagentStop payload carries agent_id; the module doc says the documented schema has none, "some builds do send it"); _normalize (about L200): nudges at or over MAX_NUDGES (3), never nudged over 1 h, or over 7 d; mark_stopped. The age and nudge rules cannot fire for an entry spawned at 18:57 and checked at 19:11 (throttle 30 min gives at most 2 charges), so by elimination (INFERRED, not proven) SubagentStop fired with agent_id when the worker ENDED ITS TURN to wait for its background command, and the entry was removed while the work continued. That fits the 47 s flip.

Structural hole (verified from dispatch.py about L2034-2040, its own docstring): the manifest tracks Agent-tool subagents only; "the repo has no mechanism tracking a raw Bash(run_in_background:true) shell"; a grep of scripts/ for run_in_background found no tracker. A worker that ends its turn to wait on a background task is invisible once SubagentStop removes it. Liveness (pending_agents.agent_is_live about L508): transcript mtime under 900 s, or under 1500 s with the last record an assistant tool_use; an ended-turn worker fails both after 15 minutes anyway.

## Candidate design (medium change; scope is an owner decision)

(a) Track background launches from the MAIN transcript at decision time: in _maybe_clear (on-stop-token-meter.py about L148) and _agents_and_interrupt_ok scan the transcript for tool_use blocks with input.run_in_background true (Bash and Agent) whose id has no later <task-notification> (transcript_roles.py about L49 already knows that prefix) and count them as live. Worker-owned background commands appear only in the worker's transcript (subagents/agent-<id>.jsonl), so also scan those via pending_agents.resolve_transcript for entries including recently-removed ones. (b) Stop deleting on SubagentStop when the agent's transcript shows an unfinished background launch, or keep a short-lived ended_ts field. New helper in pending_agents.py plus 2 call sites. Also lets the resume cue name agent and task ids (_pending_agent_directive_lines about L2829 is empty for a removed worker; the issue expected ids in the cue).

## Unverified premises (must be settled first)

1. Exact record shapes for background launches and the <task-notification> pairing (does tool_result carry the task id; is there a task-id tag).
2. Whether SubagentStop carries agent_id on the owner's Claude Code version (this decides whether removal-on-end is THE cause).
3. Evidence files to fetch (from the project where the incident happened): its .janitor/logs/subagent-stop.log and pending-agents.json history around 19:11, and the worker transcript tail.

## Test T6 (once designed)

tests/test_pending_agents_background.py: a real transcript JSONL fixture sampled from a real session (scrubbed) with a run_in_background Bash and no notification: tracker returns it live; with the notification: not live. Plus a real manifest and a real _maybe_clear (pattern of tests/test_clear_preserves_live_subagent.py: real child process, real manifest) asserting "clear deferred" when only a background launch is open.

## Approval log

- 2026-11-14T22:27:36+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
