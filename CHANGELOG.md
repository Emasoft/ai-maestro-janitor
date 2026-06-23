# Changelog

All notable changes to this project will be documented in this file.

## [0.16.0] - 2026-06-23

### Bug Fixes

- An ACTIVE session is never flagged broken (false-positive guard)
- ITerm TTY resolution — literal '|' delimiter, not the broken tab constant
- Stop false page-shape + MEMORY.md-sync findings (#54, #55)
- Exclude parked columns + age from created, not mtime (#59)
- GitHub action@sha pin is not a machine-host (#53)
- Allowlist by-design persistence + sanitizer-unicode FPs; fix agent ref path
- Trim split/record-recent skills under token caps + markdownlint ignore for internal docs
- Prune self-inflicted injection FPs + record the v0.16.0 publish blocker
- Notes/lessons/see-also are PER-ATOM — recall aggregates the full atom record (TRDD-3b9b2040)
- Show idle+age label, both metrics + first test (#59)
- Clear MD004 false-positive in wikimem-model.md (unblock publish lint gate)
- Quote two frontmatter descriptions that broke YAML parsing (CPV CRITICAL)
- Trim two over-cap descriptions under the CPV token limits (MAJOR)
- Devitalize the ATOM_PAGE test-fixture RESOURCE_ABUSE CPV false-positive
- Extract GROUP B launchd L0 OS-keepalive from the published plugin
- Clear the MAJOR/MINOR/NIT debt blocking publish (post-L0-extraction)
- Give atom-authoring.md a TOC + embed it in write SKILL (clear last NIT)

### Documentation

- Add TRDD-dccb0b8a — daemon session-liveness watchdog (out-of-session freeze recovery)
- Add TRDD-324223a6 — immortal janitor (layered self-resurrection + fault matrix)
- A3+A2 operational — record the working recovery loop (TRDD-324223a6)
- GROUP B done + audited — A+B operational immortality (TRDD-324223a6)
- Control-command matrix + Wikimem terminology (TRDD-a3fa4d5d)
- TRDD-a3fa4d5d complete — control matrix + Wikimem record shipped (committed, not pushed)
- Autonomous overnight session brain (TRDD-fe45babc)
- Night-brain — #54+#55 done, budget reality, inline-only (TRDD-fe45babc)
- Night-brain — #59 done, weekly-wall near, post-reset plan (TRDD-fe45babc)
- #56 decision (top-level ocd/lmd canonical) + fix pointer (TRDD-fe45babc)
- Night-brain — #53 done, budget exhausted, post-reset publish plan (TRDD-fe45babc)
- Leave editorial work to the janitor subconscious agent (#58, #60)
- Adopt the-skills-menu progressive-discovery architecture — backburner (TRDD-cf15d412)
- Record #56 root-cause refinement + budget-restored hold state
- Capture the CPV never-exempt policy lesson (the v0.16.0 re-block)
- Policy resolves the publish decision to (b) — separate the release
- Add TRDD-ab232dbd — MEMORY.md buffer ⇄ Wikimem coexistence (harvest-mirror)
- Record memory-coexistence architecture — separate wiki/ namespace, forward-only (TRDD-ab232dbd)
- Atom-indexing redesign — wikimem atoms as first-class index elements (TRDD-3b9b2040)
- Night-brain — record memory-redesign pivot + fresh budget (TRDD-fe45babc)
- Add verified atom-indexing blueprint — mirror the lesson-row precedent (TRDD-3b9b2040)
- Document the atom contract — block-properties, atom recall, find-claude-mem-ref — Phase E foundations (TRDD-3b9b2040)
- Teach atom authoring + atom recall in the write/recall skills (TRDD-3b9b2040)
- Mark 3b9b2040 phases e+f done + record per-atom-notes correction
- Make the ONE-memory-agent identity + dynamic single-skill loading explicit
- Record the USER's refined wikimem model (leading blocks, 4 element kinds, one agent)
- Overnight brain — wake 15:09, memory model refined+memorized, phase g held on USER confirm
- Refine 3b9b2040 model — notes/lessons/see-also are markdown footnotes + shared-footnote move rule
- 3b9b2040 phase g — g1 (leading parser) + g2 (footnote groups) DONE; g3-g6 remain
- Leading markers + footnote-grouped see-also (TRDD-3b9b2040 phase g5)
- Align recall/write/memgrep/rule docs to leading+footnote-group model (TRDD-3b9b2040 phase g6)
- 3b9b2040 phase g — g4/g5/g6 DONE; only g3 (footnote-resolve verify) remains
- Mark phase-g COMPLETE (g3 done) + record the publish blocker; clear MD004/MD053
- Refresh overnight STATE — phase-g DONE supersedes the stale "HOLD"; clear MD004
- Clear MD004 +-prose-wrap NITs in immortal + control-commands TRDDs
- Record GROUP C C1 (self-integrity manifest) landed; deferred remainder
- Accurately diagnose the publish blocker — option-b is dead (CPV #63 won't-fix)
- Record memgrep RESOURCE_ABUSE FP cleared (CPV MAJOR 6→5)
- Correct option-a scope — cd9c251 is entangled, so it's a forward-removal not a revert
- Map the publish-blocker stakes — 8/11 open issues are fixed-but-unpublished
- Record OAuth crunch (both accounts MAX) + #52 as the ready next-build

### Features

- Session-liveness detection core — pure, tested (TRDD-dccb0b8a Phase 1)
- Session records its terminal identity for the daemon (TRDD-dccb0b8a NPT)
- Full 7-rung recovery ladder + crash-loop guard (TRDD-324223a6)
- Fleet janitor-health diagnosis core (TRDD-324223a6)
- Fleet scanner — enumerate+diagnose every claude instance (TRDD-324223a6)
- /janitor-show-global-status HTML fleet dashboard + transcript-signal fix (TRDD-324223a6)
- Emoji/color legend + per-project TRDD kanban modal (TRDD-324223a6)
- Tooltips on every icon/column/cell + readability styling (TRDD-324223a6)
- A3 terminal-env-aware recovery injector (TRDD-324223a6)
- Kanban cards w/ uuid + copy buttons + TRDD-file markdown modal (TRDD-324223a6)
- A2 fleet-guardian task — autonomous freeze recovery (TRDD-324223a6)
- GROUP B OS-keepalive — the daemon itself becomes immortal (TRDD-324223a6)
- A5 nuclear recovery rungs — built INERT + default-OFF (TRDD-56d24c02)
- /janitor-stop — clean machine-wide STOP of the immortal daemon (TRDD-56d24c02)
- Global-pause mechanism + global_control_cli (disarm/arm/pause/unpause) (TRDD-a3fa4d5d)
- Control-command surface (global disarm/arm/pause/unpause) + memory-record-recent (TRDD-a3fa4d5d)
- Janitor-memory-subconscious-agent — 3-tier Wikimem editorial architecture (TRDD-aebedbff)
- Fail-safe seam synthesis — is_legal_split permits oversized seamless pages (#57, #58)
- Fail-safe seam-synthesis recipe — seamless pages always converge (#57, #58)
- Raise split_max_bytes 12k→36k + flow-style agent frontmatter
- Recall rule — MEMORY.md is the coexisting BUFFER, not a deprecated stub (TRDD-ab232dbd)
- Add find-claude-mem-ref — the harvest provenance query (TRDD-ab232dbd)
- Wiki/ namespace resolver + buffer-vs-wiki discriminator (TRDD-ab232dbd)
- Atom block-properties parser + resolver — Phase A1 of atom indexing (TRDD-3b9b2040)
- Atoms/atoms_fts index table + schema-v2 migration — Phase A2 (TRDD-3b9b2040)
- Atom-level recall — atoms interleave with pages by score — Phase C (TRDD-3b9b2040)
- Find-claude-mem-ref reads the indexed atoms.claude_mem_ref column — Phase D (TRDD-3b9b2040)
- Janitor-memory-atomize pass — migrate free-prose pages into atoms (TRDD-3b9b2040 Phase f)
- Flip atom parser to LEADING block markers (TRDD-3b9b2040 phase g1)
- Atom record groups footnotes by section — notes/lessons/see-also (TRDD-3b9b2040 phase g2)
- Enforce the shared-footnote move-rule in verify_split/merge (TRDD-3b9b2040 g3)
- Ship the file-hash manifest as a per-release artifact (TRDD-53a00e44)

### Miscellaneous

- Set +x on fleet_status.py + global_control_cli.py per shebang-script convention

### Refactor

- Rename recovery term "nuclear" → "hard-restart" (TRDD-56d24c02)

### Tests

- Cover the atomize marker in the scheduler tests + fix 6 regressions
- Flip the index test ATOM_PAGE to leading markers — completes g1 (TRDD-3b9b2040)
- Regression coverage for the #53 action-pin FP
- Fix test_trdd_detectors regression from the #59 label change

