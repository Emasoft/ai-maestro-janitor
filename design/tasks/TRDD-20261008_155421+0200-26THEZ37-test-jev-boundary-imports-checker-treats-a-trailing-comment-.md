---
trdd-id: 26THEZ37
title: test-jev-boundary imports-checker treats a trailing comment as an import (its docstring claims comment-immunity)
column: backburner
status: tasked
created: 2026-10-08T15:54:21+0200
updated: 2026-10-08T15:54:21+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-08T15:54:21+0200
---

# test-jev-boundary imports-checker treats a trailing comment as an import (its docstring claims comment-immunity)

Found by the wave-4e adversarial review of TRDD-A8DRRW0I (finding H-C): tests/test_jev_boundary.py _imports() runs its boundary regex over the whole stripped line INCLUDING any trailing comment, while its docstring claims 'a match inside a comment ... must not false-positive' — immunity holds for WHOLE-LINE comments only. Proven 2026-10-08: commit 62cac384's trailing comment '(never jev_compaction)' on pre-compact-handoff.py's jsonl_walk import line failed test_no_hook_or_named_lib_script_imports_jevctx_or_httpx for weeks of silent false-positive risk; wave 4e reworded the comment ('never the Jev one') which makes the suite green but leaves the TEST bug standing — the next import line with a trailing forbidden-module mention trips it again. Fix (failing-first): either strip trailing comments before matching in _imports, or at minimum correct the docstring to 'whole-line comments only'; add a positive control (a line with a trailing comment naming jevctx must NOT count) and a negative control (a real import of jevctx must still count). Scope: tests/test_jev_boundary.py only; no production code.

## Approval log

- 2026-10-08T15:54:21+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
