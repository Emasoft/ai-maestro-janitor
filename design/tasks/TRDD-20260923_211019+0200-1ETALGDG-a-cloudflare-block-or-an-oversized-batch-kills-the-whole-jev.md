---
trdd-id: 1ETALGDG
title: A Cloudflare block or an oversized batch kills the whole Jev compaction instead of splitting the batch
column: todo
created: 2026-09-23T21:10:19+0200
updated: 2026-09-23T23:23:38+0200
current-owner: janitor-main-session
created-by: janitor-main-session
task-type: bugfix
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: janitor-main-session
approval-datetime: 2026-09-23T21:10:19+0200
derived: true
parent-trdd: RAEGS1D5
---

# A Cloudflare block or an oversized batch kills the whole Jev compaction instead of splitting the batch

Release blocker for TRDD-RAEGS1D5 (owner 2026-09-23: no publish until a real-transcript Jev compaction passes). On 2026-09-23 the 49 MB real transcript d30bf250 failed four times with HTTP 403 Cloudflare 'Sorry, you have been blocked' from typesafe.ai (the Jev backend behind OpenRouter), at 8, 2 and 1 workers (failing after about 9 s, 58 s and 98 s), while a tiny probe succeeded right after; the same file compacted in 168 s that morning on older code. A live HTTP 400 max_tokens_exceeded also hit a 32-item batch at an estimated ~31k tokens (commit 61cad99c lowered the planner cap to 20k as a margin). Today both map to non-retried errors (403 to JevAuthError, 400 to JevValidationError), so ONE bad batch aborts the whole compaction and the session falls to llm-ext (broken, Emasoft/llm-externalizer-plugin#15) and then the template, every time, because the offending content stays in the transcript. Step 1, discriminate (costs cents): on a 403 log the failing batch index, its item ids and the response cf-ray; run the new code at 1 worker twice (same failing batch both times = content, varying = rate); send that batch alone right after a successful probe (fails = content, passes = cooldown); bisect it to one item. Step 2, if content: tell a Cloudflare block (HTML body with 'Attention Required' or a cf-ray header) from a real OpenRouter 403 (JSON error) and give it its own error kind; on that kind and on 400 max_tokens_exceeded split the batch in half and retry the halves, up to about 5 levels; an item that still fails alone is never scored or inlined, it becomes a pointer, and one finding names it. Never sanitize item text (verbatim guarantee). Tests: a fake client that blocks any batch containing one marked item still compacts the rest with that item as a pointer; a max_tokens_exceeded batch is split and succeeds. Acceptance: the 49 MB transcript compacts end to end on the final tree, with the seconds recorded against the 60 s sync and 300 s detached budgets. Corrections to commit 61cad99c's message, recorded here because history is not rewritten: its '3.14 s (was 9.6 s)' mixes card 1's smaller item count with parallel scoring; 'fewer requests' was not measured; the 403 may come from content restored by b2154831 (about 2,255 heartbeat-turn tool results), not from cards 3 and 5.

## Approval log

- 2026-09-23T21:10:19+0200 — MANDATE issued by janitor-main-session (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
