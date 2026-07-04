---
trdd-id: UENXDA8P
title: Memory-system tooling batch — is-due/mark-ran CLI, marker due-gating, verify_repair tier reconcile, frontmatter placement (issue 68)
column: todo
created: 2026-07-04T04:46:15+0200
updated: 2026-07-04T04:46:15+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 4
severity: MEDIUM
effort: M
task-type: refactor
parent-trdd: null
relevant-rules: []
release-via: publish
test-requirements: [unit, lint, typecheck]
labels: [memory-system, wikimem]
external-refs: ["https://github.com/Emasoft/ai-maestro-janitor/issues/68"]
---

# TRDD-UENXDA8P — Memory-system tooling improvements (issue #68)

## The task

Issue #68 batches four concrete wikimem-tooling gaps observed in real editorial runs. They
share one root: the subconscious agent and the skills sometimes need shell-reachable
versions of scheduler facts that today live only as Python library calls, and two verifier
behaviors drift from the documented model.

## Plan (the four issue items, one commit each)

1. **is-due/mark-ran CLI** — expose `memory_settings.is_due`/`mark_ran` through
   `memory_settings_cli.py` subcommands so skills/agents can check+stamp cadence from Bash
   without inline Python (removes the current copy-pasted `uv run -c` snippets).
2. **Marker due-gating** — the heartbeat's `[janitor-memory-*]` marker emission should
   re-verify due-ness at EMIT time (scheduler stamp could have been consumed by a parallel
   session between schedule and fire) — cheap stat, prevents duplicate agent spawns.
3. **verify_repair ↔ tier reconcile** — `verify_repair` and the repair skill's tier-shape
   rules disagree on one edge (aspect with empty Applies-to); reconcile the verifier with
   `references/wikimem-model.md` and add the missing test.
4. **Frontmatter placement** — the writer/repair paths must guarantee frontmatter is the
   FIRST bytes of a page (a BOM/blank-line prefix breaks memgrep's parser); normalize on
   write + repair, flag in librarian.

## Derived tasks

- Each item: unit test first (TDD), then fix; per-item commit with WHY.
- Re-read issue #68 verbatim before starting — the four summaries above are from the issue
  title; the issue body is authoritative on exact expected behavior.

## Verification

- All four items have failing-then-passing tests; issue #68 closed with per-item commits.
