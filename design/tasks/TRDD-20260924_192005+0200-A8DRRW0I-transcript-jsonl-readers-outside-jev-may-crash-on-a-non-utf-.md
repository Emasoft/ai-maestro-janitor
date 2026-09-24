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

Still open: other readers of the live session transcript have their own loops.
- scripts/lib/external_clear.py, the recent-turns tail on the clear/handoff path (json.loads(line) around line 641, feeding _classified_tail_lines / _tail_text_lines). Highest priority: a crash here repeats the stale-handoff class of bug.
- Hooks and libs with json.loads(line loops: scripts/agent_context_bench.py, scripts/hooks/pre-compact-handoff.py, scripts/lib/user_mem_lib.py, scripts/lib/tickets.py, scripts/lib/findings_ledger.py, scripts/lib/external_clear.py, scripts/lib/orphaned_resume.py, scripts/lib/jev_compaction.py, scripts/lib/pending_agents.py, scripts/lib/jevctx/shadow.py (grep -rln "json.loads(line" scripts, 2026-09-24; jev_compaction.py itself already uses the shared walk, kept in the list because the grep matched it).

Task: for each reader, check the open mode (text utf-8 without errors=), whether it guards against a non-dict line, and whether it skips a bad line silently or crashes. Move the transcript readers onto one shared byte-safe walk (the pattern already in scripts/lib/jev_compaction.py's iter_jsonl_entries).

## Approval log

- 2026-09-24T19:20:05+0200 — MANDATE issued by emanuelesabetta (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Related

TRDD-DQXMND59 -- Jev's own reader (extract_items/expand) was fixed there in 73df900b and 2729b1cb with the shared iter_jsonl_entries walk this card generalizes to the readers outside Jev.
