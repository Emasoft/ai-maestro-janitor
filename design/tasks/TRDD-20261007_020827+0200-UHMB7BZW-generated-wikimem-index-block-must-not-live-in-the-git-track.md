---
trdd-id: UHMB7BZW
title: Generated wikimem index block must not live in the git-tracked CLAUDE.md
column: todo
status: tasked
created: 2026-10-07T02:08:27+0200
updated: 2026-10-07T02:09:02+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T02:08:27+0200
relevant-rules: [7.1, 10.1]
---

# Generated wikimem index block must not live in the git-tracked CLAUDE.md

## Approval log

- 2026-10-07T02:08:27+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-07

NEXT ACTION: verify against current Claude Code docs which mechanism is loaded natively, consult the fable advisor (behaviour change for every project using the plugin), then write the tests first and implement.
DECISION (main session, 2026-10-07, under the owner's standing instruction to decide reversible questions): generated content does not belong in a tracked file; the block moves out of tracked CLAUDE.md. The mechanism is NOT decided.
CONFLICT TO RESOLVE FIRST: PRRD G7.1 lists the janitor-generated wikimem index fence as one of the five elements CLAUDE.md MUST contain, and G10.1 requires every root topic to appear in the CLAUDE.md wikimem index. Both are GOLDEN (user-only). Moving the block out needs a user-approved proposal amending G7.1 and G10.1 before implementation.
Candidate mechanisms to evaluate: (a) a gitignored CLAUDE.local.md that Claude Code loads natively; (b) an import line in CLAUDE.md of a gitignored generated file; (c) a SessionStart hook injecting the index as additional context with no file at all. The implementer must verify against current Claude Code docs which is loaded.

## Background

GitHub janitor#328 (reported by the Claude responsible for the ai-maestro-webdesign project): the SessionStart hook writes a generated block, fenced by JANITOR-WIKIMEM-INDEX-START/END markers with a digest= and generated= stamp, into the project's tracked root CLAUDE.md. It showed dirty in status, got swept into by-file commits, and the committed digest goes stale.
Already fixed: 980c3891 (shipped in v3.8.0) — the block is rewritten only when its digest changes; test_cli_index_consecutive_runs_leave_claude_md_byte_identical in tests/test_claudemd_slim.py pins byte-identical consecutive runs. The writer is scripts/lib/repomap/claudemd_slim.py (WIKIMEM_FENCE_START/END); scripts/detectors/project-map-drift.py and tests/test_claudemd_queue.py also reference the fence.
Still true: the block changes whenever PROJECT memory changes, so the tracked file still goes dirty then and a committed copy still goes stale.

## Acceptance

- [ ] The block is no longer written into any tracked file
- [ ] An existing block in a tracked CLAUDE.md is removed once (migration) without touching other content
- [ ] Claude still sees the index at session start (verified live)
- [ ] A test pins that the plugin never writes into a tracked file
- [ ] PRRD G7.1 and G10.1 amended by the user, or the proposal refused and this card closed accordingly
- [ ] janitor#328 closed with a comment naming the commits
