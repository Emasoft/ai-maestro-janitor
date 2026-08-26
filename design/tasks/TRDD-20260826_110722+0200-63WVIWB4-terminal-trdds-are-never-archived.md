---
trdd-id: 63WVIWB4
title: 272 terminal TRDDs sit in design/tasks because nothing ever performs the archival step
column: backburner
created: 2026-08-26T11:07:22+0200
updated: 2026-08-26T11:07:22+0200
current-owner: janitor-main-session
task-type: infra
project-id: ai-maestro-janitor
scope: project
severity: minor
min-approval-requirement: none
labels: [board, trdd, archival, hygiene]
npt: []
eht: []
implementation-commits: []
relevant-rules: []
---

# The archival step of the TRDD lifecycle has effectively never run in this repo

## Measured 2026-08-26

```
column: complete    197
column: published    75      → 272 terminal cards, all in design/tasks/
column: backburner   25
column: blocked      16
column: todo          6
column: planned       3
column: human_review  3
column: testing       1
```

```
design/tasks/     326 files
design/archived/   20 files
design/refused/     3
design/proposals/   0
```

So **272 of the 326 files in `design/tasks/` are terminal**, while `design/archived/` holds 20.
The TRDD rules say every terminal column archives AS ITSELF into `design/archived/`
(archive-eligible = `complete|completed|cancelled|superseded|published|live`), and the approval
rules define an OPEN TRDD as exactly one that lives in `design/tasks/`. By that definition this
repo reports 326 open cards and actually has 54.

## Why it stayed invisible

**There is no archiver.** `grep -rln "design/archived" scripts/` returns exactly one file,
`fleet_status.py`, and only as a legend string describing what the folder means. No script, no
detector, no skill performs the `git mv`. The archival protocol is documented as a manual step
inside the promotion/refusal/archival procedures, and manual steps at the END of a workflow are
the ones that get skipped — the card is finished, the interesting part is over, and nothing
fails if the move never happens.

Nothing breaks day to day, which is the other half of why it persisted: `findtrdd`-style lookups
scan every lifecycle folder, so a terminal card in the wrong folder is still findable. The cost
is only paid by anything that counts or lists OPEN work — including a human asking "what is on
the board".

## What this is NOT

Not a claim that any individual card is mis-columned. Every one of the 272 correctly says what
it is; they are simply in the wrong folder. That distinction matters for the fix: this is a
mechanical relocation keyed on `column:` alone, NOT the per-card judgment the kanban rule warns
against scripting.

## ⚠ Why it was not just done

272 `git mv`s change 272 paths in one commit. Paths appear in reports, in other cards' prose, in
commit messages, and in any handoff that cited a filename. The moves are recoverable (git tracks
renames) and the ids are unchanged, so nothing is *lost* — but a restructuring of that size on a
board the owner reads is a decision about their working surface, not a tidy-up an agent should
perform unprompted while doing something else.

The narrow, safe version is also available: archive only `published` (75), which are the least
likely to be re-read, and leave `complete` alone.

## Acceptance

- [ ] A decision on whether to relocate (all / `published` only / leave in place and redefine
      what `design/tasks/` means)
- [ ] If relocating: one commit, `git mv` only, keyed on `column:` — no content edits in the
      same commit, so the rename detection stays clean and the diff is reviewable
- [ ] Whatever is decided, the recurrence is closed at the source: either an archiver runs the
      move, or a detector reports terminal cards left in `design/tasks/`. A rule that relies on
      a human remembering the last step of a workflow has already been measured failing 272
      times.

## Notes and lessons learned

Found while reading TRDD-87RKBYJ8, whose four split children are all terminal and all still in
`design/tasks/` — which is what prompted counting the rest.

[^1]: [id: LESSON-63WV-1, status: active, keywords: board_shows_hundreds_of_open_cards how_many_trdds_are_actually_open archived_folder_almost_empty terminal_cards_in_tasks_folder open_work_count_is_wrong kanban_looks_overloaded, ocd: 2026-08-26, lmd: 2026-08-26]
    DO NOT read the file count of `design/tasks/` as the amount of open work, BECAUSE the
    archival `git mv` is a manual final step that has been skipped 272 times — the folder holds
    every finished card too. DO count by `column:` (`grep -h "^column:" design/tasks/*.md |
    sort | uniq -c`), which is the field that cannot drift from what the card says about itself.

[^2]: [id: LESSON-63WV-2, status: active, keywords: documented_step_never_happens process_relies_on_remembering last_step_of_workflow_skipped nothing_fails_when_it_is_missed silent_process_decay, ocd: 2026-08-26, lmd: 2026-08-26]
    DO NOT close a workflow with a manual step whose omission breaks nothing immediately,
    BECAUSE the omission is then invisible for months — here it accumulated to 272 before anyone
    counted. DO make the last step either automatic or observable, and prefer observable when
    the action itself deserves a human decision.
