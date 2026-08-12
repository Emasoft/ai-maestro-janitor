---
trdd-id: F4IBIDB6
title: Nothing detects a WORK column that nobody is working — the sweep has been done by hand twice in one day
column: todo
created: 2026-08-13T00:58:36+0200
updated: 2026-08-13T01:07:00+0200
current-owner: unassigned
task-type: feature
approval-tier: 0
scope: project
severity: medium
relevant-rules: []
npt: []
eht: []
external-refs: [TRDD-WP7TCRME]
implementation-commits: [3f15a8ee]
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
- [ ] The stale-WORK-column check names candidates and their idle age, and states the invariant
      rather than proposing a destination
- [ ] Neither check MUTATES a card
- [ ] A card that is genuinely being worked right now does not fire (the false-positive that
      would get the whole thing switched off)
