---
trdd-id: 71M8MIAM
title: split of a footnote-bearing atom lands the [^N] reference on the wrong half — suspected mem_split verb behavior
column: backburner
status: tasked
created: 2026-09-26T11:22:34+0200
updated: 2026-09-26T11:31:30+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-09-26T11:22:34+0200
---

# mem_split verb misplaces footnote markers when a split separates the paragraph carrying them

- Symptom: the 2026-09-26 PROJECT split chore (c4744261) split ATOM-ZG19-ZDYA and dropped the [^1] footnote reference on the triage half instead of the settings-traps half (ATOM-APUY-M2DB) that discusses the lesson's subject (ATOM-57J4-RKKB, the naive CLAUDE_CODE_PROJECT_DIR_NAME fix). Hand-fixed in 5d219d6b via update-mem-topic; the tool itself is unfixed.
- Suspected location: scripts/memgrep (Rust), split-mem-atom verb, around mem_split.rs:592-602 (lmd-bump block) — the splitter partitions body paragraphs but has no reference-following behavior for [^N] markers whose definition lives in a different atom.
- Scope: (a) make split-mem-atom move a footnote marker with the paragraph whose subject the referenced lesson guards, or at minimum flag a split that separates a marker from its referenced subject; (b) residue from the same split — ATOM-ZG19-ZDYA still recalls on CLAUDE_CODE_PROJECT_DIR_NAME / the_LOCAL_memory_dir_points_at_the_wrong_path keywords while its body no longer discusses them (keyword partition never completed); (c) minor: hand edit-path did not bump lmd on the two touched atoms, inconsistent with the tool path.
- Found by adversarial review fork on 5d219d6b, 2026-09-26.

## Approval log

- 2026-09-26T11:22:34+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Disposition (review round 2)

Title retitled to symptom level — the mem_split.rs location is SUSPECTED, not verified; the splitter may move the marker with the paragraph it lexically ends on and the real defect could be the pre-split placement. (b) and (c) are SECONDARY scope: closing (a) alone must not close this card. (b) verified 2026-09-26 (ZG19 recalls 2 rows on CLAUDE_CODE_PROJECT_DIR_NAME); its fix is a content decision for the memory chore lane. (c) minor. Implementer note: the flag-only fallback (flag a split that separates a marker from its referenced subject) is likely the implementable option; semantic subject-resolution may not be mechanically derivable.
