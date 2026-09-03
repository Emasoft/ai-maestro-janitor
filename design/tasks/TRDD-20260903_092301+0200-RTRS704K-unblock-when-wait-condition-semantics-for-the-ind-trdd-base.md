---
trdd-id: RTRS704K
title: decide and document unblock-when wait-condition re-evaluation semantics in the IND TRDD base — descriptive blockers like owner-decision-x must become machine-checkable
column: testing
created: 2026-09-03T09:23:01+0200
updated: 2026-09-03T11:05:00+0200
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

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-03T11:05:00+0200

Boxes 1-2 DONE with proof below. Box 3 (janitor#288 reply + ai-maestro notify) is deliberately
**untouched** — out of this worker's scope (it belongs to whoever posts on GitHub; see the
orchestrator's own dispatch note). **NEXT ACTION:** post box 3 (answer janitor#288 with a link
to the shipped rule text + open a notify issue on Emasoft/ai-maestro), then move to
`human_review`/`complete` per normal TRDD flow. The installed `~/.claude/rules/…` copy is NOT
edited here — it syncs from `rules/` on the next plugin publish (per repo convention); nothing
further to do on that half of box 1.

Proof:
- Rule text: `rules/trdd-design-tasks.md` (new `## unblock-when:` section) +
  `rules/references/trdd-design-tasks-full.md` (`unblock-when:` schema line + new subsection,
  citing and superseding F4IBIDB6 for new cards) — 37 lines total, both files agree.
- Code: `scripts/lib/trdd_common.py` (`unblock_when_predicates`, `pre_block_column`) +
  `scripts/detectors/trdd-drift.py` (`_evaluate_predicate`, `evaluate_unblock_when`,
  `_restore_column_text`, `_try_unblock`, wired into `main()` for every `column: blocked`
  card). `issue:` reads only `issues-watch-seen.json` + `git remote get-url origin` — no
  network call per fire.
- Tests: `tests/test_trdd_common_unblock_when.py` (6) + `tests/test_trdd_drift_unblock_when.py`
  (31, one-plus per predicate kind + malformed + `decision:` end-to-end) — 37/37 pass; full
  scoped suite (+ the 3 pre-existing trdd-drift/trdd_common files) 183/183 pass. `ruff` +
  `mypy --ignore-missing-imports` clean on both touched source files.

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

- [x] Rule text + full reference updated; the janitor's shipped copy under `rules/` says it —
      the installed `~/.claude/rules/trdd-design-tasks.md` syncs on the next plugin publish
      (the janitor owns this rule per `three-pillars-rules-ownership`).
- [x] `trdd-drift.py` evaluates the non-human predicate kinds and restores
      `pre-block-column:` when one turns true (test per kind).
- [ ] janitor#288 answered with a link to the shipped rule text; ai-maestro notified via an
      issue on Emasoft/ai-maestro (no direct edits to that repo). **Deliberately left for the
      orchestrator** — out of this worker's scope per its dispatch instructions.

## Approval log

- 2026-09-03T09:23:01+0200 — filed under USER delegation 2026-09-03 (~09:10, "decide yourself,
  you can replace me even in human review columns") by janitor-main-session.

## Constraints (advisor review 2026-09-03)

- `issue:<owner/repo#N> closed` must NOT hit the network per card per fire. Evaluate it from
  the snapshot `_open_issues_bit` already keeps (`dispatch.py:2824-2828`); treat a predicate
  naming an issue in another repo as `decision:` until a cross-repo snapshot exists.
- `file:`/`log:` predicates on a PROJECT card are a scope-leak vector — the card is
  git-tracked and pushed, so an absolute or out-of-repo path leaks local layout to every
  cloner. Allow only repo-relative paths.
- "`blocked-by:` keeps only TRDD/issue references" must cite and supersede the F4IBIDB6
  accommodation at `scripts/lib/trdd_common.py:581-590` (`has_blocked_by_value` deliberately
  accepts non-TRDD-shaped blockers because most real blockers on this board aren't cards) —
  the rule text change needs to say explicitly how that accommodation is retired or narrowed.

## Notes and lessons learned
