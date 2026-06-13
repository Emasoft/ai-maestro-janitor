---
trdd-id: 4c3733d9-479b-4926-8ada-2b0b51895164
title: Memory scope locations — USER to PLUGIN_DATA done, PROJECT to .claude-project-memory, LOCAL harness
column: dev
created: 2026-06-13T17:23:05+0200
updated: 2026-06-13T17:23:05+0200
current-owner: amama
assignee: amama
task-type: refactor
release-via: publish
test-requirements: [unit]
relevant-rules: [4]
labels: [memory, scope, storage-location]
---

# TRDD-4c3733d9 — Memory scope storage locations (3-scope redesign + content install)

## STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-13T17:23:05+0200

LOCKED CONFIG (USER decision 2026-06-13 — see memory notes
feedback_user_memory_in_plugin_data + feedback_memory_cooperate_with_harness):

| Scope | Folder | Status |
|---|---|---|
| USER/global | ${CLAUDE_PLUGIN_DATA}/memory/ (janitor plugin DATA dir) | DONE — committed 3b3cf52 |
| PROJECT | <repo>/.claude/project/memory/ (in-repo, namespaced, git-tracked via gitignore exception) | TODO |
| LOCAL | ~/.claude/projects/<slug>/memory/ (harness slug path) | unchanged (cooperate w/ harness) |

WHY (load-bearing): cooperate with the harness — it owns LOCAL (writes there for every
agent); the janitor ADDS USER + PROJECT (the harness defines neither). USER in PLUGIN_DATA
= untouchable/backed-up/--keep-data + ONE canonical copy (no 16x duplication of global
wikimem). PROJECT under .claude/ because memory/ is a very common GitHub root-folder name
(inevitable collision); .claude/.../memory is collision-free.

### NEXT ACTION (PROJECT migration — same shape as the USER one in 3b3cf52)
Change PROJECT root <repo>/memory/ to <repo>/.claude/project/memory/ in:
1. rules/markdown-memory-recall.md (PROJECT_MEM + table + prose) — the SHIPPED source.
2. skills/janitor-memory-{recall,write,update}/SKILL.md (PROJECT path).
3. scripts/detectors/memory-scope-leak.py (the PROJECT root it scans + its git-tracked check).
4. scripts/detectors/memory-librarian.py (PROJECT root resolver).
5. scripts/hooks/on-prompt-submit-autorecall.py (PROJECT root resolver).
6. NEW: gitignore-exception logic — where .claude/ is ignored, ensure !.claude/project/ +
   !.claude/project/memory/ + !.claude/project/memory/** ; the scope-leak detector already
   verifies PROJECT memory is git-tracked, so it surfaces a missing exception.
7. tests: test_autorecall_hook.py (PROJECT test write path), test_memory_scope_leak.py.
All-or-nothing (PROJECT memory is empty everywhere, no notes to lose, but keep files consistent).

### THEN: content install (drafts in reports/memory-audit/, ~2150 lines)
- USER fleet hub ai-maestro-fleet-hub.draft.md to ${CLAUDE_PLUGIN_DATA}/memory/.
- PROJECT wikimems (janitor-architecture, publish-pipeline, memory-system, the rotation page
  — dedupe its 3 backoff variants) to <repo>/.claude/project/memory/ + commit; scope-leak
  detector then validates no private data.
- LOCAL promotions per local-22-classification.md (7 keep / 9 to PROJECT / 6 to USER w/ redaction).
- Fleet rollout: ship a /janitor-memory-bootstrap skill + one coordination issue per repo
  (each project's own Claude populates its tracked memory/ — janitor never edits other repos).

### Durable artifacts to read before acting
- memory notes: feedback_user_memory_in_plugin_data, feedback_memory_cooperate_with_harness.
- drafts + analysis: reports/memory-audit/ (fleet-memory-survey.md, local-22-classification.md).
- the USER migration commit 3b3cf52 (the exact pattern to mirror for PROJECT).

## Origin
USER directive across 2026-06-13: audit the memory system, install fleet-wide, get the
USER/PROJECT/LOCAL levels right. Settled the 3-scope storage config above.
