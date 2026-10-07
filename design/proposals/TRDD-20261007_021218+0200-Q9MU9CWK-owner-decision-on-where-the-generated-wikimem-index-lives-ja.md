---
trdd-id: Q9MU9CWK
title: Owner decision on where the generated wikimem index lives (janitor#328)
column: proposal
status: proposed
created: 2026-10-07T02:12:18+0200
updated: 2026-10-07T04:44:35+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: user
assignee: main-agent@ai-maestro-janitor
approved: false
relevant-rules: [7.1, 10.1]
---

# Owner decision on where the generated wikimem index lives (janitor#328)

## Approval log

## STATE

NEXT ACTION: owner picks (a), (b) or (c). (b) and (c) then need: verify the mechanism against current Claude Code docs, consult the fable advisor, tests first.
OWNER DECISION NEEDED — three options: (a) keep G7.1/G10.1 and close #328 with a comment stating that CLAUDE.md still changes whenever PROJECT memory changes because the PRRD requires the index there; (b) keep G7.1/G10.1 and narrow the block so it changes only when a ROOT topic changes (G10.1 requires root topics only), cutting most of the residual churn without a rules change; (c) amend G7.1/G10.1 and move the block out of the tracked file — stating whether the project-map fence, which G10.1 also requires, moves too, since it has the same tracked-file problem.
Replaces TRDD-UHMB7BZW, which was minted pre-approved by the main session and could not be moved back to proposals.
Golden PRRD rules G7.1 and G10.1 require the wikimem index fence in CLAUDE.md and are user-only, so no agent may decide this.
2026-10-07: owner decision still open; nothing changed today; default is to wait: change nothing and leave issue 328 open.

## Background

GitHub janitor#328 (reported by the Claude responsible for the ai-maestro-webdesign project): the SessionStart hook writes a generated block, fenced by JANITOR-WIKIMEM-INDEX-START/END markers with a digest= and generated= stamp, into the project's tracked root CLAUDE.md. It showed dirty in status, got swept into by-file commits, and the committed digest goes stale.
Already fixed: 980c3891 (shipped in v3.8.0) — the block is rewritten only when its digest changes; test_cli_index_consecutive_runs_leave_claude_md_byte_identical in tests/test_claudemd_slim.py pins byte-identical consecutive runs. The writer is scripts/lib/repomap/claudemd_slim.py (WIKIMEM_FENCE_START/END); scripts/detectors/project-map-drift.py and tests/test_claudemd_queue.py also reference the fence.
Still true: the block changes whenever PROJECT memory changes, so the tracked file still goes dirty then and a committed copy still goes stale.

## Acceptance

- [ ] Owner chose (a), (b) or (c), recorded verbatim in this card
- [ ] If (b) or (c): the block changes only on root-topic changes (b) or is no longer written into any tracked file (c)
- [ ] If (c): an existing block in a tracked CLAUDE.md is removed once (migration) without touching other content
- [ ] If (b) or (c): Claude still sees the index at session start (verified live)
- [ ] If (b) or (c): a test pins the chosen behaviour
- [ ] janitor#328 closed with a comment naming the commits
