---
trdd-id: G5GY101S
title: The janitor column vocabulary lags 3-pillars 3.0.0 — five columns missing, one phantom
column: complete
created: 2026-08-27T22:50:00+0200
updated: 2026-08-28T12:42:14+0200
current-owner: janitor-session
task-type: bugfix
project-id: ai-maestro-janitor
min-approval-requirement: none
relevant-rules: [2]
---

# The janitor column vocabulary lags 3-pillars 3.0.0

Raised by the ai-maestro hub (alignment request, 2026-08-27; spec 3.0.0 at ai-maestro
`governance-rules` 13e7bb02 / HEAD 62dd0b64).

## Verified gap

- `scripts/lib/trdd_common.py` `ALL_COLUMNS` (line ~259) lacks the five 3.0.0 additions
  `approval`, `design_ai_review`, `design_human_review`, `verify_assumptions`, `plan`,
  and carries a phantom `archived` that is not in the legal 27-value set (3P-KAN-20).
- `rules/trdd-design-tasks.md` §6 still says "The 17-column vocabulary" — the shipped
  `rules/universal-kanban.md` already says 22 / 27.
- NOT a runtime defect today: `trdd-drift` keys only on `ACTIVE_COLUMNS` (skips unknown
  columns, never flags them), `is_pipeline_value` has no caller outside its test. The
  constant is the vocabulary SSOT and drifts silently; fix before any consumer keys on it.

## Acceptance

- [x] `ALL_COLUMNS` == the 27-value legal set, ordered as the spec lists them; `archived` gone.
- [x] Decide whether `ACTIVE_COLUMNS` (drift staleness set) gains `approval`/`plan`/
      `verify_assumptions` — they are work columns under 3.0.0 (`design` precedes `todo`).
- [x] `rules/trdd-design-tasks.md` §6 cites 22 columns / 27 legal values; rules byte cap holds
      (53699/53700 — reclaim margin first, see agent-handoff).
- [x] `uv run pytest tests/test_trdd_common.py tests/test_rules_installer.py` green.

## Notes and lessons learned

- 2026-08-27 — `ALL_COLUMNS` is now the 27-value legal set (five 3.0.0 columns added; the phantom
  `archived` removed — it names a FOLDER, never a column). `rules/trdd-design-tasks.md` §6 says
  22-column; the swap was byte-neutral, so the 1-byte rules-cap headroom was never touched.
  Verified: 255 TRDD tests + 36 rules-installer tests pass, ruff + mypy clean.
- 2026-08-28 — ACTIVE_COLUMNS WIDENED to all five, on ai-maestro's measured position (hub session
  ai-maestro-91): on the largest live 3.0.0 corpus, 196 open cards, only `approval` is populated
  (4 cards) and the other four are at zero — so the blast radius is 4 cards today and grows every
  month. Two classes, both in scope: `verify_assumptions`/`plan` are assignee-active (a stopped
  worker is precisely what drift looks for); `approval`/`design_ai_review`/`design_human_review`
  wait on an approver, and since `blocked` is the only licence to sit still and an approval queue
  carries no `blocked-by:`, an un-drained queue currently reads as healthy.
- The hub's "approvals legitimately wait days, so give them 7d" concern needs no per-column
  threshold here: trdd-drift has ONE shared threshold, default **14 days**
  (`CLAUDE_PLUGIN_OPTION_TRDD_STALENESS_DAYS`), already longer than the 7d it asked for, and
  `review-after:` is the sanctioned per-card snooze. No second mute was built.
- Its `updated:`-clock caveat does not apply to this detector, verified in source: staleness is
  judged from the **git last-commit timestamp** (`file_mtime` fallback for uncommitted/LOCAL
  cards), never from `updated:` — `trdd-drift.py:220` says so outright. A mechanical repair that
  does not bump `updated:` therefore cannot skew the clock either way.
- Blast radius here: ACTIVE_COLUMNS has exactly ONE consumer, `trdd-drift.py:33`. `trdd-reminder`
  and `on-session-start-trdd-state` keep their own narrower WORK-only sets and are untouched.

## Approval log

- 2026-08-28T12:42:14+0200 — COMPLETED. All four acceptance boxes re-verified first-hand before
  closing, not taken from the notes: `ALL_COLUMNS` is the 27-value set with `archived` gone
  (`trdd_common.py:277-286`), `ACTIVE_COLUMNS` carries all five 3.0.0 additions (`:253-266`),
  and `pytest tests/test_trdd_common.py tests/test_rules_installer.py` → 131 passed.
  **Box 3 closed as HALF-LITERAL, deliberately.** Its text asks §6 to cite "22 columns / 27 legal
  values"; `rules/trdd-design-tasks.md:82` cites the 22 and delegates ("the 22-column vocabulary
  lives in `universal-kanban.md`"), and the 27 is stated one hop away at `universal-kanban.md:51`
  — so a reader following §6 reaches the correct legal set. NOT patched to name 27 inline: the
  shortest byte-neutral rewording still costs +3 B against 1 B of installed headroom under
  `_RULES_FLOOR_CAP_BYTES` (53,700), and that floor is re-written into cache by every cold
  subagent machine-wide. Growing it to satisfy a wording is the wrong trade; if someone later
  "notices §6 doesn't say 27", the reclaim comes first. The card had sat
  at `column: dev` with every box already ticked — done but unclosed, which reads identically to
  abandoned. Not yet `git mv`-ed into `design/archived/`: the owner has not authorized commits and
  a staged rename among 82 uncommitted paths would be noise. Archive it with the commit pass.

