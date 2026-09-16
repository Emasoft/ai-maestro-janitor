---
trdd-id: RTRS704K
title: decide and document unblock-when wait-condition re-evaluation semantics in the IND TRDD base — descriptive blockers like owner-decision-x must become machine-checkable
column: complete
created: 2026-09-03T09:23:01+0200
updated: 2026-09-03T23:38:32+0200
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
implementation-commits: [f512540f, 3fe3b0e2]
external-refs: [janitor#288, ai-maestro#158, ai-maestro TRDD-2UPK4XZG]
created-by: issue triage 2026-09-03
---

# unblock-when semantics for the IND TRDD base

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-03T11:07:44+0200

- **Advisor-review hold-fixes landed (4 defects, all confirmed and fixed):**
  1. `column_by_uid` in `trdd-drift.py::main()` is now built across every `trdd_common.DESIGN_FOLDERS`
     entry (tasks/archived/proposals/refused), not `tasks/` alone — a blocker that shipped and was
     archived used to be invisible to the board, holding its dependent blocked forever.
  2. New `trdd_common.DONE_COLUMNS`/`is_done_column` (`complete`/`completed`/`published`/`live`) —
     the `blocked-by:` hold in `_try_unblock` now requires the blocker to have actually SHIPPED, not
     merely reached any terminal column (`failed`/`refused`/`cancelled`/`superseded` stay a hold).
     `unblock-when: trdd:<id> terminal` keeps its documented `is_terminal_column` semantics (untouched).
  3. `log:` predicate tail-window fix: when the 256 KiB seek-from-end lands mid-line, the window
     DROPS everything up to and including its first `\n` before matching, so `^` can never land
     on a line fragment the truncation cut in half. (The worker's first cut prepended a `\x00`
     sentinel instead; the orchestrator replaced it because `^.*needle` swallows a sentinel and
     still matches the fragment — the test now asserts that pattern too. Ceiling: a window with
     no `\n` at all — one >256 KiB line — matches nothing; the tail filler in the tests is
     newline-terminated for that reason.)
  4. Comment at the `blocked_by_ids` skip in `_try_unblock` corrected: it silently drops BOTH
     issue refs (`owner/repo#N`) AND descriptive tokens (`owner-decision-x`), not just issue refs
     — `unblock-when: decision:` is the documented machine-checkable replacement for both.
  - Tests: `tests/test_trdd_common_unblock_when.py` +3 (`is_done_column` true/terminal-not-done/open),
    `tests/test_trdd_drift_unblock_when.py` +4 (`holds_when_blocked_by_is_terminal_but_not_shipped`,
    `column_by_uid_spans_all_design_folders`, `log_predicate_tail_boundary_does_not_false_match_a_cut_line`,
    `log_predicate_tail_boundary_still_matches_a_real_line_start`) — 7 new, 206/206 pass in the scoped
    gate (`trdd-drift`/`trdd_common`/`dispatch_phases` test files). `ruff` + `mypy --ignore-missing-imports`
    clean on both touched source files.

- **Bounded follow-up landed:** `_try_unblock` now also checks `blocked-by:` before restoring
  — a still-open OR unresolvable blocked-by TRDD id holds the card blocked even when every
  `unblock-when:` predicate is satisfied (mirrors dispatch.py's `_blocked_reason`). The `log:`
  predicate now reads only the last 256 KiB of the target file (seek-from-end) instead of the
  whole file, bounding both I/O and worst-case regex backtracking on a large `.janitor/logs/`
  file re-evaluated every heartbeat. 6 new tests added; `ruff`/`mypy --ignore-missing-imports`
  clean; full scoped suite 62/62 pass.

**Second advisor pass (2026-09-03, later) — 5 more defects fixed:**
  - B1: `open_issue_numbers` is now `set[int] | None` end to end (`_evaluate_predicate`,
    `evaluate_unblock_when`, `_try_unblock`, and `main()`'s snapshot-load block default to
    `None`). Previously a missing/unreadable snapshot left an EMPTY set, and
    `num not in set()` is always True — every `issue:` predicate on the project's own repo
    auto-satisfied the moment the watcher snapshot was absent. `None` now returns `False`
    (not satisfied) explicitly, distinct from an empty-but-present snapshot (which correctly
    still satisfies). Also documented the 50-open-issue snapshot cap at the predicate site.
  - B2: `_restore_column_text` now also clears `blocked-by: []` and drops the
    `pre-block-column:` line on restore — previously both were left behind, so
    `check4_stale_blockers` re-flagged the already-cleared blocker id every fire.
  - B3: documented (reference doc only, `trdd_common.parse_flow_list` untouched) — a comma
    inside a `log:` regex (`\{2,3\}`, `a,b`) silently splits into malformed tokens; fails
    safe (stays blocked) but not what the author meant.
  - B4: `_try_unblock` now validates `pre-block-column:` against `trdd_common.ALL_COLUMNS`
    (and refuses `"blocked"` itself) before writing it as the restore target — a
    typo'd/corrupted value now holds the card blocked with a log line instead of writing an
    illegal `column:`.
  - D5: restored the "residue is a VALUE, never the field NAME" clause to
    `rules/trdd-design-tasks.md` step 6 — 2 lines, corpus total 53,504 B, still under the
    53,700 B installer cap (`test_shipped_rules_stay_under_the_context_floor_cap`).
  - Tests: `tests/test_trdd_drift_unblock_when.py` +5 (missing-snapshot / empty-snapshot
    issue predicate, blocked-by+pre-block-column cleared on restore, illegal
    pre-block-column holds). Scoped gate (`trdd-drift`/`trdd_common`/`dispatch_phases`/
    `rules_installer`) 246/246 pass; `ruff` + `mypy --ignore-missing-imports` clean on both
    touched source files.

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
- [x] janitor#288 answered with a link to the shipped rule text; ai-maestro notified via an
      issue on Emasoft/ai-maestro (no direct edits to that repo).
      janitor#288 comment `5532171186` links the rule text pinned at `f512540f`; ai-maestro#158
      carries the two semantics fixes back (SHIPPED-not-merely-terminal `blocked-by:` holds, and
      indexing blockers across every design folder) plus the `log:` tail-window newline detail.

## Approval log

- 2026-09-03T09:23:01+0200 — filed under USER delegation 2026-09-03 (~09:10, "decide yourself,
  you can replace me even in human review columns") by janitor-main-session.
- 2026-09-03T23:38:32+0200 — COMPLETE. Reviewed by the janitor main session under the owner's standing delegation of the review columns (2026-09-03). Every acceptance box verified against the code, not taken from the card's own word.

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
