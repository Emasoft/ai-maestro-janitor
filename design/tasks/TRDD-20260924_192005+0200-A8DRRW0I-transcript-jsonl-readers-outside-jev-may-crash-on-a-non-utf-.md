---
trdd-id: A8DRRW0I
title: Transcript JSONL readers outside Jev may crash on a non-UTF-8 byte or a half-written line
column: backburner
status: tasked
created: 2026-09-24T19:20:05+0200
updated: 2026-09-24T19:20:18+0200
current-owner: emanuelesabetta
created-by: emanuelesabetta
task-type: bugfix
min-approval-requirement: none
assignee: emanuelesabetta
mandate: true
mandated-by: none
approved: true
approval-judge: emanuelesabetta
approval-datetime: 2026-09-24T19:20:05+0200
---

# Transcript JSONL readers outside Jev may crash on a non-UTF-8 byte or a half-written line

Fixed: Jev's own transcript reader was fixed in 73df900b and 2729b1cb with a shared iter_jsonl_entries in scripts/lib/jev_compaction.py (byte-safe, survives non-UTF-8 bytes and a half-written last line).

Scope, redefined 2026-09-24 (review of the first draft): code that opens the live Claude Code session transcript -- a session's own transcript, or a background/subagent's own live transcript (both are the same JSONL shape and carry the same non-UTF-8/torn-line risk) -- and parses it itself. Excludes a caller that only resolves/forwards a transcript_path to another function (dispatch.py, clear_trigger.py, terminal_trigger.py, on-session-start-post-clear-compact.py, pre-tool-context-usage.py, pre-tool-token-budget.py, jev_compact.py: all delegate, none parse). Excludes the janitor's own NDJSON ledgers, which are a different file family that happens to share the .jsonl extension (tickets.py's dispatch-ledger.jsonl, findings_ledger.py's own ledger), Jev's own shadow log (jevctx/shadow.py's jev-shadow.jsonl), and a test fixture (agent_context_bench.py's tests/agent_context_bench/corpus.jsonl). Found via grep -rnE "transcript_path|transcript\.open|\.jsonl" scripts, 2026-09-24, then each hit read to classify it as reader/delegator/other-ledger.
- scripts/lib/external_clear.py -- _classified_tail_lines / _tail_text_lines, the recent-turns tail on the clear/handoff path. Highest priority: a crash here repeats the stale-handoff class of bug.
- scripts/hooks/pre-compact-handoff.py -- _recent_turns.
- scripts/lib/user_intent.py -- recently_interrupted (walks the transcript backwards in growing windows looking for an Esc/Ctrl-C marker).
- scripts/lib/token_meter.py -- detect_fire_kind, tail_turn_usage, latest_context_size (all via the shared _read_tail_lines).
- scripts/lib/jev_compaction_lane.py -- _scan_transcript_mentions (one streamed pass over the WHOLE transcript, not just the tail).
- scripts/lib/fleet_scan.py -- transcript_activity (reads the tail via _tail_lines, then substantive_age_from_tail / awaiting_user_decision).
- scripts/lib/pending_agents.py -- _last_transcript_entry_has_tool_use and spawn_prompt, both reading a background/subagent's OWN agent-<id>.jsonl transcript. CORRECTION to the dispatching instructions, which said this file reads only the janitor's own ledgers: it does NOT -- these two functions genuinely open and json.loads a live Claude Code transcript (verified by reading the code, 2026-09-24); it stays in scope.
- scripts/lib/user_mem_lib.py -- previous_user_message, reading transcript_path taken straight from the UserPromptSubmit hook payload (scripts/hooks/on-prompt-submit-user-mem.py:158, payload.get("transcript_path")) -- the literal live session transcript, not a janitor ledger. CORRECTION to the dispatching instructions, which said this file reads only the janitor's own ledgers: it does NOT (verified by reading the code and its one caller, 2026-09-24); it stays in scope.
Already safe, no fix needed here: scripts/lib/orphaned_resume.py's project_root_from_transcript already opens with errors="replace" and guards isinstance(rec, dict) before use -- confirmed by reading the code, 2026-09-24. Already fixed, not open: scripts/lib/jev_compaction.py (this card's own "Fixed" paragraph above).

Task: for each reader, check the open mode (text utf-8 without errors=), whether it guards against a non-dict line, and whether it skips a bad line silently or crashes. Move the transcript readers onto one shared byte-safe walk.

Design constraint: the shared walk lives in a NEW stdlib-only module, scripts/lib/jsonl_walk.py, extracted from scripts/lib/jev_compaction.py's iter_jsonl_entries under TRDD-DQXMND59 stage 3. A hook MUST import jsonl_walk, never jev_compaction directly -- jev_compaction pulls in jevctx and httpx, and that import cost on a hook's own start-up is what caused the 2 s timeouts (TRDD-D7RLXAN1's heartbeat-stagger follow-up). The janitor's own NDJSON ledgers (tickets.py, findings_ledger.py) may adopt jsonl_walk too, as a separate, optional item -- not required for this card.

## Approval log

- 2026-09-24T19:20:05+0200 — MANDATE issued by emanuelesabetta (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Related

TRDD-DQXMND59 -- Jev's own reader (extract_items/expand) was fixed there in 73df900b and 2729b1cb with the shared iter_jsonl_entries walk this card generalizes to the readers outside Jev.
