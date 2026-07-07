---
trdd-id: UENXDA8P
title: Memory-system tooling batch — is-due/mark-ran CLI, marker due-gating, verify_repair tier reconcile, frontmatter placement (issue 68)
column: complete
created: 2026-07-04T04:46:15+0200
updated: 2026-07-07T17:32:26+0200
implementation-commits: [0c0f64d, 6a1c04b, 2f6063b]
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

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-07

ALL FOUR ITEMS RESOLVED; TRDD terminal.
- **P1 SHIPPED** (`0c0f64d`): `is-due`/`mark-ran` verbs on memory_settings_cli
  (exit 0 due / 1 not-due / 2 error; UPPERCASE-normalized scope labels so the
  stamp key can't fork; `--root`/`--now` escape hatches; 5 new tests).
- **P2 ALREADY FIXED by closed #50** — verified in code: memory-maintenance gates
  each marker on `memory_settings.is_due` AT EMIT TIME and stamps BEFORE emitting
  under the machine-wide dispatch flock (detector lines ~218-320). Nothing to do.
- **P3 SHIPPED** (`6a1c04b`): verify_repair no longer requires `tier` — absent ⇒
  component per the model; explicit junk tiers still rejected.
- **P4 SHIPPED** (`2f6063b`): canonical key-placement section added to
  wikimem-model.md (serializer half was ced38b4/#56 + d63f31a/#33).

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
