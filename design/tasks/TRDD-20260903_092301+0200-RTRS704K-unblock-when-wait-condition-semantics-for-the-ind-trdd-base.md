---
trdd-id: RTRS704K
title: decide and document unblock-when wait-condition re-evaluation semantics in the IND TRDD base — descriptive blockers like owner-decision-x must become machine-checkable
column: todo
created: 2026-09-03T09:23:01+0200
updated: 2026-09-03T09:23:01+0200
current-owner: janitor-main-session
task-type: docs
priority: normal
severity: low
scope: project
project-id: ai-maestro-janitor
min-approval-requirement: none
labels: [trdd, kanban, rules, ind-base, blocked]
relevant-rules: []
blocked-by: []
npt: []
eht: []
implementation-commits: []
external-refs: [janitor#288, ai-maestro TRDD-2UPK4XZG]
created-by: issue triage 2026-09-03
---

# unblock-when semantics for the IND TRDD base

## Why now

The 2026-09-03 blocked-cards audit
(`reports/board-drain/20260903_091543+0200-blocked-cards-audit.md`) found 10 of 21 blocked
cards carrying a DESCRIPTIVE `blocked-by:` token (`owner-decision-c3-selfheal-caller`,
`awaiting-live-429-observation`, `user-present-supervised-hard-restart-trial`, …) that no
tool can evaluate. They are legal under the current rule text and invisible to every drain
mechanism — TRDD-1PDCPIZC now flags them `decision-needed`, but the rule itself still allows
a blocker nobody can clear mechanically. janitor#288 asked the same question upstream
(ai-maestro TRDD-2UPK4XZG, `reports/architect/20260820_193931+0200-spec-wait-condition-recheck-trdd.md`).

## Decision to make (this card)

Adopt an `unblock-when:` field in the IND base (`rules/trdd-design-tasks.md` + the full
reference): a machine-checkable predicate — `trdd:<id> terminal`, `issue:<owner/repo#N>
closed`, `file:<path> exists`, `log:<path> matches <regex>`, `date:>=YYYY-MM-DD`,
`decision:<who>` (the only human-only kind, and it MUST be surfaced by the attention cue) —
re-evaluated by `trdd-drift` on every fire; `blocked-by:` keeps only TRDD/issue references.
Existing descriptive tokens migrate to `unblock-when: decision:<who>` on next touch.

## Acceptance

- [ ] Rule text + full reference updated; the janitor's shipped copy under `rules/` and the
      installed `~/.claude/rules/trdd-design-tasks.md` say the same thing (the janitor owns
      this rule per `three-pillars-rules-ownership`).
- [ ] `trdd-drift.py` evaluates the non-human predicate kinds and restores
      `pre-block-column:` when one turns true (test per kind).
- [ ] janitor#288 answered with a link to the shipped rule text; ai-maestro notified via an
      issue on Emasoft/ai-maestro (no direct edits to that repo).

## Approval log

## Notes and lessons learned
