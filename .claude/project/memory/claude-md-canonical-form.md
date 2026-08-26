---
name: claude-md-canonical-form
description: "what is allowed to live in CLAUDE.md / why was my paragraph moved out of CLAUDE.md into a wikimem page / the canonical five-element shape and the automatic migration chore that enforces it / is it ok to add a paragraph to CLAUDE.md / why is CLAUDE.md so small / where should project knowledge live instead of CLAUDE.md / who moves text out of CLAUDE.md / does the janitor clean CLAUDE.md automatically / is the CLAUDE.md auto-migration chore built yet / which TRDD implements the CLAUDE.md migration chore / why does every session re-read CLAUDE.md on every turn / what is the token cost of a paragraph parked in CLAUDE.md / what are the five allowed elements of CLAUDE.md / the project-map fence and the wikimem index fence are machine-owned / preservation proof before removing lines from CLAUDE.md / a nudge is not enforcement"
ocd: 2026-08-04
lmd: 2026-08-26
metadata:
  node_type: memory
  type: project
  tier: component
  globs: [CLAUDE.md, scripts/claudemd_slim.py, scripts/lib/repomap/claudemd_slim.py, scripts/repomap_generate.py]
publish-globally: false
---

# claude-md-canonical-form


^ATOM-4BV1-6FAF [desc:"CLAUDE.md holds exactly five elements and nothing else, because every line in it is re-read on every turn of every session", keywords: what_can_go_in_CLAUDE.md why_was_my_text_removed_from_CLAUDE.md is_it_ok_to_document_this_in_CLAUDE.md CLAUDE.md_is_too_big where_should_project_knowledge_live_instead_of_CLAUDE.md slim_claude_md_canonical_structure why_is_CLAUDE.md_re-read_on_every_turn what_are_the_five_allowed_elements how_much_did_a_heartbeat_fire_cost_re-reading_CLAUDE.md what_is_the_G9.1_exemption_list never_hand-edit_between_the_fence_markers, ocd: 2026-08-04, lmd: 2026-08-04]

`CLAUDE.md` is an INDEX, not a knowledge store. Owner directive (2026-08-02, re-stated 2026-08-04; PRRD G7.1): it holds EXACTLY five elements, in order — (1) a one-paragraph project description, (2) the project URLs, (3) the dev-ops commands, (4) the janitor-generated project-map fence, (5) the janitor-generated wikimem index fence. Both fences are machine-owned: never hand-edit between the markers. Everything outside them is the "narrative" and is budgeted — this repo's is 1,029 bytes, down from 48,165 (TRDD-H12K9JYX, migration commit 1f42f77). WHY SO STRICT, and this is the whole argument: `CLAUDE.md` is injected into EVERY session's context on EVERY turn, and a turn re-reads that context once per tool call — measured, one heartbeat fire re-read it 6 times for 3,239,112 tokens / $1.72. So a paragraph parked here is not paid once, it is paid per turn, per tool call, per agent, forever, INCLUDING by every agent for whom it is irrelevant. A wikimem page inverts that: it costs nothing until a symptom query asks for it. The exemption under G9.1 is a CLOSED list — git, commit, branching, merging, linting, building, testing, tagging, pushing, CI, publishing, installing, deploying — and may not be extended by analogy. Spec: `design/specs/claude-md-canonical-form.md`. See [[memory-system]] and [[janitor-beat-tasks-and-limitations]].


^ATOM-EUB0-EL5I [desc:"a line added to CLAUDE.md must be MIGRATED OUT automatically by the scheduled chore, not merely warned about", keywords: who_moves_text_out_of_CLAUDE.md does_the_janitor_clean_CLAUDE.md_automatically a_nudge_is_not_enforcement migration_chore_turns_claude_md_lines_into_atoms preservation_proof_before_removing_lines why_did_memorize-nudge_fall_silent how_is_it_proven_that_nothing_was_lost_in_migration what_is_claudemd_slim_verify does_removing_narrative_change_the_map_fence why_must_the_index_stay_complete_after_migration, ocd: 2026-08-04, lmd: 2026-08-04]

A line appearing in `CLAUDE.md` outside the five elements is a DEFECT TO REPAIR, not a warning to surface (PRRD G8.1). The janitor's scheduled chore must: detect the excess narrative → RECALL the wikimem page that owns the subject (never mint a duplicate) → write it as a new atom OR fold it into the owning atom plus a `[^N]` lesson learned → remove the migrated lines → PROVE nothing was lost before committing. WHY AUTOMATIC AND NOT ADVISORY — the failure mode is already measured on this repo: `memorize-nudge` gated on WHEN a note was last written rather than WHAT was uncaptured, so it fell silent while seven commits of new mechanism went unrecorded, and the mechanism was then re-derived wrongly two days later (fixed 2026-08-04, `db7a6c5f`). A rule enforced only by an agent noticing a reminder is not enforced. PRESERVATION IS PROVEN, NEVER ASSUMED: `claudemd_slim verify --old <pre-migration file>` must show every fact line and load-bearing token survived, and the map fence must be byte-identical when only narrative moved — the 2026-08-02 migration was accepted exactly that way (150,823 bytes compared, oracle re-run from git history). `memgrep validate` + `lint` must pass on every touched page. Index completeness is part of the contract (G10.1): a root topic missing from the index fence is unreachable, which would make the migration a knowledge SHREDDER rather than a mover. Status + the approved card: see the implementation-status atom on this page (WM-ATOM-09).


^ATOM-SY5J-SXZ4 [desc:"IMPLEMENTATION STATUS as of 2026-08-04 — the automatic CLAUDE.md migration chore is SPECIFIED but NOT BUILT; the approved card is TRDD-LFSWY0C6", keywords: is_the_CLAUDE.md_auto_migration_implemented does_the_janitor_actually_move_lines_out_of_CLAUDE.md_yet which_TRDD_builds_the_claude_md_migration_chore specified_but_not_built what_is_the_janitor-memory-claudemd_marker is_conformance_still_advisory_only is_TRDD-LFSWY0C6_done_yet what_card_should_I_check_for_migration_status how_do_I_tell_decided_from_built what_is_the_approved_card_TRDD-LFSWY0C6, ocd: 2026-08-04, lmd: 2026-08-04]

STATUS 2026-08-04 — the automatic migration required by PRRD G8.1 is SPECIFIED, NOT BUILT. What exists today is the canonical form itself plus the tooling that CHECKS it (`claudemd_slim check` / `verify`, the fence surgery, the index renderer — TRDD-H12K9JYX, complete) and an ADVISORY nudge on `project-map-drift`. The nudge is precisely what G8.1 rules out, so conformance currently depends on an agent noticing a reminder. APPROVED CARD TO BUILD IT: **TRDD-LFSWY0C6** (`column: todo`) — a new intervention in the memory-maintenance scheduler with a `[janitor-memory-claudemd]` marker routed to the subconscious agent, reusing the existing `claudemd_slim` primitives. This atom exists per WM-ATOM-09: a spec-stage claim MUST name the card in flight, so a reader can tell DECIDED from BUILT and can reach the work. Per WM-ATOM-10, when LFSWY0C6 lands this atom is SUPERSEDED — never rewritten, never deleted — by one describing the actual implementation, and LFSWY0C6 travels DOWN into the superseded body where it belongs to the historical claim rather than the current one.

## See also

- [[git-index-lock-orphan-recovery]] — the inverse of this page's nudge failure: a
  fail-closed subsystem that CANNOT accumulate visible incidents, where the
  commit-count nudge is the only signal that can exist.

## Notes and lessons learned
