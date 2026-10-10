---
trdd-id: UASBYABI
title: Should the keep-going board nudge name only cards owned by the receiving session
column: complete
status: archived
created: 2026-10-09T23:23:38+0200
updated: 2026-10-11T00:46:57+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-09T23:23:38+0200
---

# Should the keep-going board nudge name only cards owned by the receiving session

Carried out of TRDD-LH84WTL5 when it closed on 2026-10-09. That card fixed two sessions of one project being woken onto the same board (a lease, TTL 2700 s). It left one design question open: the nudge lists the whole open board, so a session is told about cards it was never assigned, which sits badly with the rule that a session takes no work without an explicit assignment. Decide from facts: how often the nudge reaches a session whose own cards are all closed, and what the receiving session then does.

## Acceptance

- [x] The current nudge text and its card selection are read from scripts/dispatch.py and quoted here.
- [x] A decision is recorded with its basis: keep the whole board, or filter to the session's own cards, or name owned cards first.

## Approval log

- 2026-10-09T23:23:38+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-11T00:46:57+0200 — COMPLETE by main-agent@ai-maestro-janitor. decision recorded with its basis: keep the whole board.

## Findings

2026-10-11 00:46 (clock). READ by the main session in scripts/dispatch.py (HEAD 597e00d4; git log on the file run first: last nudge change is 9b2b1299, TRDD-W4IZA704, which did not touch card selection). TEXT, _board_summary_bit (line 3472): 'open board: N in <column> (TRDD-a, TRDD-b, TRDD-c +K more); ... — finishing a card means pulling the next', joined into 'continue your pending task (keep-going mode) — ...' by _phase_keep_going_nudge. SELECTION: every card file under design/tasks of the project root whose column is in _WORK_COLUMNS (todo, verify_assumptions, plan, dispatch, dev, testing, ai_review, publish, deploy, live_auditing); per column the count and the first three ids in alphabetical order. No ownership field is read. DECISION: KEEP THE WHOLE BOARD. BASIS: (1) 'cards owned by the receiving session' cannot be computed: no card records a session id; current-owner and assignee are free-text role names, and on this board the one main session appears under at least eight spellings (main-agent@ai-maestro-janitor 149 cards, janitor-main-session 58, ai-maestro-janitor 48, janitor-session 20, claude-ai-maestro-janitor 13, amama 8, janitor-dev-session 6, janitor-claude 6); two other projects on this machine show the same pattern (ai-maestro, AgentlensPro). A filter on any one spelling would hide most of the board from its only worker. (2) The base kanban rule for a project without the harness is one assignee, the project's own Claude, so every open card is that session's card. (3) Two sessions of one project are already kept apart by the lease of TRDD-LH84WTL5. NOT MEASURED, and not measurable from the logs for reason (1): how often the nudge reached a session whose own cards were all closed, and what it then did. NOT ADDRESSED: the nudge names ids in alphabetical order, not the ranked next card; the hint 'trddgrep next' added by TRDD-W4IZA704 covers that once released. REOPEN IF cards gain a session or agent id that the dispatcher can compare (the harness overlay).
