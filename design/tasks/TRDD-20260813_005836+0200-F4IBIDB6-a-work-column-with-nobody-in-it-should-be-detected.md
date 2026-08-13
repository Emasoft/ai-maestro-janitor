---
trdd-id: F4IBIDB6
title: Nothing detects a WORK column that nobody is working — the sweep has been done by hand twice in one day
column: complete
created: 2026-08-13T00:58:36+0200
updated: 2026-08-13T05:04:00+0200
current-owner: unassigned
task-type: feature
approval-tier: 0
scope: project
severity: medium
relevant-rules: []
npt: []
eht: []
external-refs: [TRDD-WP7TCRME]
implementation-commits: [3f15a8ee, 6a0066d7]
---

# The board-honesty sweep has no owner but a human

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative)

**Filed to discharge the `report-to-trdd` drift line on
`reports/board-honesty/DECISIONS-recolumn-stalled-work-cards.md` (2026-08-12 15:25), and the
detector was right to fire even though the decisions had already landed.** Reports are
gitignored and ephemeral; the DECISIONS in that one are durable — verified, all 8 applied, each
card carrying its own `RE-COLUMNED <old> → <new>` Approval-log line — but nothing in `design/`
cited the report, so from the board's side the work looked unconverted. This card is the
citation, and the finding it leaves behind.

**The finding: the sweep itself has no owner.** It has now been performed BY HAND TWICE inside
ten hours — that report at 15:25, and again at 00:2x (`451e3f2f`, five more false claims
including one of my own from an hour earlier). Both passes found real lies on the board. Nothing
schedules it, so it happens when a human or a session happens to look.

**What exists and does NOT cover this:**
  - `trdd-drift` / `trdd-reminder` surface IDLENESS (*"8 TRDD(s) active … idle 10d"*) — age,
    not the claim a column makes.
  - `trdd-state-reconciliation` surfaces SHIPPED-but-open (commits in a released tag while the
    card is non-terminal) — a different lie.
Neither asserts the invariant the pipeline rule actually states: **a card in
`dev`/`testing`/`ai_review` claims someone is working it RIGHT NOW**, and `blocked` claims a
non-empty `blocked-by:`.

## Why this must SURFACE and not auto-fix (Rule 3's decision margin)

The 15:25 report is the argument, in its own words: the correct destination differs per card —
`backburner` for one waiting on a condition nobody can manufacture ("needs a real human"),
`todo` for one simply unstarted, `blocked` only when a blocker can be NAMED. It also warns
against exactly the shortcut an auto-fixer would take: *"a board-wide `sed` over prose it cannot
parse would destroy the audit trail this pass exists to restore."*

So the deliverable is a detector that states the untrue claim and names the candidates, leaving
the destination to whoever reads it. That is a report the janitor can produce for free, on every
heartbeat, instead of when someone remembers to look.

## Sketch

Extend `trdd-state-reconciliation` (it already parses every card's frontmatter, so the marginal
cost is one predicate) rather than adding a detector:

  - a card in a WORK column whose `updated:` is older than N days AND whose git mtime shows no
    recent touch → *"claims active work, nothing has touched it in Nd"*;
  - a card at `column: blocked` with an empty or absent `blocked-by:` → *"claims blocked, names
    no blocker"* (this one is objective and needs no threshold — it was 2 of 9 blocked cards
    tonight, including one I had written an hour earlier).

## Acceptance

- [x] The empty-`blocked-by:` check ships first — **SHIPPED `3f15a8ee`** as Check 6.
      Writing its test found a bigger defect: `blocked_by_ids` extracts TRDD-shaped ids only,
      so the 5-of-9 cards naming a non-TRDD blocker (`ai-maestro#102`, `publish-of-7ceab3f`)
      would all have fired — the exact false-positive storm the last box warns about. The
      predicate is now `has_blocked_by_value`, and the same defect was fixed in
      `has_stated_precondition`, where it had been making trdd-drift nag correctly-parked cards.
      Superseded box text — it is exact, needs no threshold, and caught a
      real case the same night it was noticed
- [x] The stale-WORK-column check names candidates and their idle age, and states the invariant
      rather than proposing a destination — `check7_work_column_without_work`, fired as
      `work-column-without-work`, shipped at 6a0066d7.
- [x] Neither check MUTATES a card — pinned by
      `test_reconcile_reports_check7_without_mutating_the_record`, which compares every record
      field before and after.
- [x] A card that is genuinely being worked right now does not fire — pinned at 0d AND at the
      2.99d boundary, plus `test_check7_is_scoped_to_the_columns_that_make_the_claim`.

## ⏵ STATE — 2026-08-13: complete. Shipped at 6a0066d7 (check 6 had shipped earlier at 3f15a8ee).

**The sweep now runs free on every heartbeat.** It had been performed BY HAND three times in
under a day — the 15:25 report, `451e3f2f` at 00:2x, and again this session on UA4FAX67, which
sat in `todo` while both its remaining boxes were outside anyone's effort. Every pass found real
lies. That is the definition of a chore with no owner.

**Two design points, both aimed at the one fatal failure mode** (firing on a card somebody IS
working, which gets a board detector switched off wholesale):

1. `_idle_days` takes the **freshest** of two signals — frontmatter `updated:` and the file's
   real mtime. Either alone produces that false positive: an agent mid-work edits the body
   without bumping `updated:` (mtime fresh, stamp stale), while a mechanical repair bumps
   neither reliably. The minimum means any recent evidence of activity keeps the card quiet.
2. Threshold 3d, deliberately generous, with the boundary (2.99d) pinned.

**Age is INJECTED**, like check 1's `commit_in_released_tag` and check 4's `column_of`, so the
predicate stays pure. `None` ⇒ silent: an unknown age is not evidence of a stall, and inventing
one would accuse exactly the cards whose metadata is hardest to read.

**Surfaces, never mutates** — the destination genuinely differs per card, and the report that
motivated this warned that a board-wide scripted pass "would destroy the audit trail this pass
exists to restore".

**Note for whoever sees the first firing:** the board carries ZERO cards in `dev`/`testing`/
`ai_review` today, so check 7 is correctly silent right now. Its guards are synthetic by
necessity; it will speak the first time a WORK card is left untouched for 3 days.
