---
trdd-id: ICB4GTHI
title: Measure whether CLAUDE_PROJECT_DIR is the launch path or the realpath
column: backburner
status: tasked
created: 2026-10-23T17:55:40+0200
updated: 2026-10-23T22:29:26+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-23T17:55:40+0200
relevant-rules: [13, 14, 15, 24]
spec: wikimem-layout-spec.md 0.2.8
---

# Measure whether CLAUDE_PROJECT_DIR is the launch path or the realpath

Spec: design/specs/wikimem-layout-spec.md 0.2.8 (draft). VERIFY-1 restated: in a session launched through the ~/Code symlink, determine whether CLAUDE_PROJECT_DIR holds the logical launch path or the physical path. Not measured anywhere. Blocks: WL-3 for hooks and WL-5 worktree writes. Done when: the measurement is recorded as a fact in the spec's WL-FACT section with its evidence.

## Approval log

- 2026-10-23T17:55:40+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-23T22:29+0200 — PARTIAL RESULT, card stays open (main session): read-only evidence (reports/board/20261023_222904+0200-ICB4GTHI-verify1.md) INFERS that CLAUDE_PROJECT_DIR holds the logical launch path, not the realpath: in session 20d63f12, launched through the ~/Code symlink, the SessionStart hook printed /Users paths, its code reads the unresolved variable, and the git fallback would have printed /Volumes. The variable itself was never printed, and the plugin code that ran (3.6.3/3.7.0) is no longer on disk. Owner rule G26 forbids deciding on inference, so this is not recorded as a spec fact. NEXT: one direct reading, a session launched through ~/Code that prints CLAUDE_PROJECT_DIR from a hook or a Bash call; run it when the host is not overloaded.
