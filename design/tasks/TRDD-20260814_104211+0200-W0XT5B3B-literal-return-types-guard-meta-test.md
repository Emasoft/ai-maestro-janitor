---
trdd-id: W0XT5B3B
title: Literal return types plus a refusal-reachability meta-test for every guard
column: todo
created: 2026-08-14T10:42:11+0200
updated: 2026-08-14T10:42:11+0200
current-owner: janitor-main-session
task-type: infra
approval-tier: 0
scope: project
severity: medium
relevant-rules: []
npt: []
eht: []
external-refs: [janitor#245]
---

## Body

The guards already speak a machine-readable vocabulary
(`clear_stale_index_lock` returns "absent"/"held"/"live-git"/"no-snapshot"/
"too-young"/"raced"/"error"/"removed"). Annotate such returns as
`typing.Literal[...]` so pyright polices the docstring's enum for free, then
add a meta-test in the style of `tests/test_git_optional_locks_guard.py`: for
EVERY guard function with a Literal return, every member of that Literal must
appear as an ASSERTED EXPECTED VALUE somewhere in tests. This mechanically
forces each refusal path to be reachable and tested — the defect being
prevented is a fail-closed branch that no test can distinguish from deleted
code.

**Acceptance:** the meta-test FAILS when a Literal member is added with no
asserting test (prove it, like the existing scanner self-test does).

## Notes and lessons learned

Origin: senior advisor review, filed per janitor#245.
