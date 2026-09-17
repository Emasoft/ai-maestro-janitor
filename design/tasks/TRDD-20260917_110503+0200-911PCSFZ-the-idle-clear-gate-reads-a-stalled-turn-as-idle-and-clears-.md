---
trdd-id: 911PCSFZ
title: the idle-clear gate reads a stalled turn as idle and clears a session with live subagents using a stale handoff
column: backburner
created: 2026-09-17T11:05:03+0200
updated: 2026-09-17T11:28:13+0200
current-owner: Emasoft
created-by: Emasoft
task-type: spike
min-approval-requirement: none
assignee: Emasoft
mandate: true
mandated-by: none
approved: true
approval-judge: Emasoft
approval-datetime: 2026-09-17T11:05:03+0200
---

# the idle-clear gate reads a stalled turn as idle and clears a session with live subagents using a stale handoff

SYMPTOM: at 10:10 the idle-clear gate (idle-clear-fired.ts) typed /clear into session 02237db5 while that session was STUCK in a heartbeat turn that started 08:54 and produced no output for 83 minutes (queued prompts only). OBSERVABLES ONLY — the gate's decision code was NOT read: idle-clear-fired.ts = 10:10:24; the session's last assistant text 08:53, last user entry 08:54 with three prompts queued behind it; three lean-workers alive; handoff-clear-verify.json recorded context_tokens 416582 and handoff_link_count 0. Which predicate fired is unknown. The session had three live lean-workers (spec+card, two memory pages, full pytest) which were orphaned; two were half done, the pytest result was never reported. The new session received the 04:07 handoff (5471 bytes, zero links, 'no task in flight') because no fresh handoff existed at clear time; the llm-ext summary of the cleared session landed at 10:17 and surfaced only via the 10:28 [janitor-resume] fire. Evidence: reports/board-drain/20260917_105900+0200-post-clear-closeout.md, .janitor/state/handoff-clear-verify.json (before: context_tokens 416582, handoff_link_count 0).
DEFECT: (a) the gate does not distinguish a stalled turn from an idle session; (b) after the clear, nothing re-attached the post-clear session to the three live subagents: the [janitor-resume] fire listed none of them, pending-agents.json still listed them as not stopped at 10:21 and had dropped them by 10:40 with no session ever consuming their results — TRDD-7MGJYLY5 proves the subagent PROCESS survives a clear; this is the missing re-attachment, a continuity defect, not a prohibition on firing; (c) it injects whatever handoff exists instead of refusing or composing one.
WHERE: scripts/lib/external_clear.py, scripts/lib/cold_cache_compact.py (CLEAR_ENABLED_ENV = CLAUDE_PLUGIN_OPTION_IDLE_CLEAR_ENABLED).
ACCEPTANCE: [ ] a session whose transcript's last entry is a queued prompt or a still-open tool call is never cleared (observable, mechanism to be established by reading the gate); [ ] a session with running subagents in pending-agents.json is never cleared; [ ] a clear never proceeds when the newest handoff predates the session's last assistant text; [ ] tests pin all three.
RELATED: TRDD-L32WC0H7 (stalled heartbeat fire, nudge ladder) covers the stall but not the clear; TRDD-7MGJYLY5 (clear preserves live subagent) covers the harness surviving a clear, not the gate's decision to fire.

## Approval log

- 2026-09-17T11:05:03+0200 — MANDATE issued by Emasoft (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
