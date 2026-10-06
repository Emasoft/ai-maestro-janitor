---
trdd-id: DS3WDTPV
title: Clear path injects a continuity block with the last request and own reply
column: testing
status: tasked
created: 2026-10-03T03:41:46+0200
updated: 2026-10-06T18:44:50+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: manager
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-03T03:41:46+0200
project-id: ai-maestro-janitor
parent-trdd: K9AHY1ZB
derived: true
implementation-commits: [cc48b42f, 10a763b8, b8cbfe61]
---

# Clear path injects a continuity block with the last request and own reply

### C2 — continuity block on the clear path
1. **Dead code first**: `tldr dead hooks/pre-compact-handoff.py`, committed alone.
2. **Move** `_build_continuity_record` and its helpers, with their constants, to `scripts/lib/session_continuity.py` using `fastedit move-to-file`. Update the test imports in `tests/test_precompact_handoff_hook.py` (`_hook()` :46 loads by path; only `_TRANSCRIPT_ROLES_IMPORT_ERROR` and `_MAX_BACKWARD_SEEK_SECONDS` are monkeypatched). No compatibility re-exports.
3. **Clear-only fields** (everything through `state.sanitize_for_drift_line`):
   - `last_user` = the last human record, via `jev_compaction.is_human_record` (`:450`), excluding heartbeat prompts (`transcript_roles.HEARTBEAT_PREFIX`) and automation commands.
   - `own_reply` = the **first** assistant text after it, up to ~800 chars. This skips later heartbeat replies without classifying them.
   - `goal` = the last `goal_status` with `met:false`.
   - `plan_file` = included only if it exists; mentioned, not read.
   - `open_tasks` = from `~/.claude/tasks/<oldStem>/*.json`, where status is not completed.
4. **NEXT ACTION**: add a `HandoffInputs.next_action` field (`lib/external_clear.py:1607`, rendered at `:1662-1678`) with no heuristic:
   > "The user's last message was «last_user». Your reply was «own_reply». If your reply asked the user something, ask it again and stop. Otherwise continue from it."

   Card STATE is the fallback only when `last_user` is empty.
5. **`## Continuity` block**, placed ahead of the Jev text: goal, open tasks, "re-invoke skills: …", plan file, live agents, open-file paths.
   - It has its own budget inside `LANE_INJECTION_MAX_BYTES` (8192 < the documented 10,000), applied through `jcl.trim_cards_for_room` (`:775`).
   - The native-compaction `_continuity_nudge` stays untouched (R2 ruling).
- **Tests:**
  - A synthetic fixture shaped like 89d835ac: human "have you fixed the rotator?", an assistant reply ending "reply go …", then 4 heartbeat turns. NEXT ACTION quotes that reply and never "janitor heartbeat". Fails before.
  - Goal, task and skill fixtures.
  - The block survives a large Jev text within budget.
  - No sidecar (a user-typed `/clear`) produces no block.
  - The source=compact output is byte-identical before and after.
- **Verify**: SC, plus the real hook run as a subprocess with a temp HOME, with stdout inspected.

Parent plan: TRDD-K9AHY1ZB

## Approval log

- 2026-10-03T03:41:46+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-10-05 — Code is in v3.7.0 (cc48b42f). RESUME POINT. Column testing. NAMED LIVE EVENT: the first janitor clear on an installed release carrying it, with a sidecar present, where the injected handoff must show a Continuity block and a NEXT ACTION quoting the last human message and the agent's own reply.
2026-10-05 — the status line above was appended here by mistake; the card's STATE section now holds it.

## STATE

2026-10-05 — Code is in v3.7.0 (cc48b42f). RESUME POINT. Column testing. NAMED LIVE EVENT: the first janitor clear on an installed release carrying it, with a sidecar present, where the injected handoff must show a Continuity block and a NEXT ACTION quoting the last human message and the agent's own reply.
2026-10-06: NEXT ACTION wording changed in 10a763b8 (plus a no-task clause in the next commit): a resumed session no longer re-asks and stops; it continues the task in flight, doing only steps that do not depend on the answer, never the action the question gates; with no task in flight it asks again and waits. Measured cause: a 29 min idle on 2026-10-06. NAMED LIVE CHECK: after the release, a janitor clear whose last reply ended on a question is followed by a turn that makes at least one work tool call. Other idle causes: TRDD-K60FT7PJ.
2026-10-06: b8cbfe61 added the no-task clause (with no task in flight, ask again and wait). Both commits ship in v3.7.1. Sessions already running keep the old SessionStart hook until they reload, so the named live check must use a session started after the update.
2026-10-06: v3.7.2 published (82a81908). NEXT: when its CI is green, update the janitor plugin from the ai-maestro-plugins marketplace at user scope on the dev host (the claude plugin update command), then perform the named live check.
2026-10-06: v3.7.3 published (14e56db3); the local update waits for its green CI.
