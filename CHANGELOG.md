# Changelog

All notable changes to this project will be documented in this file.

## [0.32.0] - 2026-07-08

### Bug Fixes

- Recency-gate daemon_needs_restart so an older cache can't seize a newer daemon (TRDD-FVO2KSSO)
- Map [janitor-reload] to /janitor-reload-plugins in the cron prompt (issue #70, TRDD-GB3Z9U9J)
- Count usage ONCE per message id — per-entry summing inflated turns 2.1-3.7x (user bug report)
- Verify_repair accepts tier-less pages — absent means component (issue #68 P3, TRDD-UENXDA8P)
- S1b guard excludes daemon-owned runtime churn (code-review xhigh finding)
- Executable bit on reports-purge.py — the heartbeat exec()s detectors directly (caught by test_detector_executable_bits)
- H-1 merge-into-survivor verify blind spot + H-2 abort destroying a committing journal (wikimem audit)
- Close the 3 privacy-leak HIGHs — memgrep walk exclusion + fail-closed hook + fitted time budgets (wikimem audit F8-F11)
- The 5 instruction-surface HIGHs from the wikimem audit (H1-H5)
- Enforce is_legal_merge/is_legal_split at commit time (wikimem audit libs M-2)
- Roll-forward preserves concurrent edits — hash-guard _apply writes/deletes (wikimem audit libs M-1)
- Harden resume_pending — per-journal isolation, orphan-staging sweep, mtime-based staleness (wikimem audit libs M-7, M-8, M-9)
- Validate txn rel-paths against scope-root escape (wikimem audit libs M-10)
- Parse_frontmatter supports block-style YAML lists (wikimem audit libs M-4)
- Settings robustness — float-modulo phase + coerce-on-load (wikimem audit libs M-5, M-6)
- Route scope-root re-derivations through the memory_scopes SSOT (wikimem audit libs M-11)
- Autorecall sanitizes injected lines + filters non-note files (wikimem audit runtime F14, F15)
- Memgrep walk excludes the non-note family — *-proposed.md reports filtered engine-side (wikimem audit runtime F16)
- Scope-leak detector — tracked-only bounded LOCAL-shape scan + stale proposal clearing (wikimem audit runtime F18, F19)
- Librarian recurses via the SSOT scan + keys notes/links on rel paths (wikimem audit runtime F20)
- Central defang of forged reserved markers in detector stdout (wikimem audit runtime F6)
- Pending-pick sidecar pins the stamped (scope, root) for the fanned-out agent (wikimem audit runtime F1)
- Execution-context banners say Sonnet, not opus (wikimem audit skills M1)
- Txn CLI invocations resolve via $CLAUDE_PLUGIN_ROOT (wikimem audit skills M2)
- Conflict skill matches the real CLI ops + executor toolset (wikimem audit skills M3, M7)
- Consolidate step-1 recency listing actually works (wikimem audit skills M4)
- Forged-marker defense on consolidate + harvest; correct consolidate's marker name (wikimem audit skills M9)
- Harvest stamps claude_mem_ref/hash provenance; split backlink query uses the slug (wikimem audit skills M6, M11)
- Main-agent skills declare page bodies untrusted (wikimem audit skills M10)
- Per-project rr-cursor + fail-open catch-all + flushed marker (wikimem audit runtime F2, F3, F5)
- Flock-serialize memory_settings' two read-modify-write sites (wikimem audit runtime F4 = libs L-12)
- Edit-verify LOW batch — L-2 heading-stop, L-3 full-line heading, L-4 fence mask, L-5 per-id dangling refs, L-6 fence-state dupes (wikimem audit libs)
- Txn CLI — L-7 op cross-check, L-8 --unsplittable, L-9 overview pick, L-10 abort-on-shape-error (wikimem audit libs)
- Migrate plan records skipped notes (L-13) + regression tests for the libs LOW batch
- Trdd_id8_re accepts 8-char base36 ids, not hex-only (wikimem audit skills L5)
- Wikimem/ home unified across write/bootstrap/harvest + LOWs L1-L9 (wikimem audit skills, M5 USER decision 2026-07-08)
- [janitor-resume] gets the whole-line-only marker contract (wikimem audit runtime F7)
- Close the whitespace-bypass + argv-exposure privacy gaps (wikimem audit runtime F12, F13)
- Memory-correction advisory covers MultiEdit (wikimem audit runtime F22)
- Daily state-dir sweep bounds seen-file/stamp growth (wikimem audit runtime F21)
- MD029 audit-skill 1b indent + MD004 harvest plus-prose (publish gate)
- Restructure the log-dir re-pin as an audited read-modify-write (CPV ENV_INJECTION, TRDD-82OP4EN9 publish gate)
- Clear 3 CPV NITs - TRDD wrapped plus-line + missing TOCs (publish gate, TRDD-82OP4EN9)
- Embed merge-page-rules full TOC in consolidate Resources (CPV MINOR, publish gate)

### Documentation

- Add TRDD-FVO2KSSO — align janitor with CC 2.1.181->2.1.200 (plan only)
- D-G alignment notes for CC 2.1.181-2.1.200 (TRDD-FVO2KSSO)
- 2026-07-04 evaluation — 8 TRDDs for the open shortcomings
- Board-reconciliation sweep steps 1+2 — close 12 shipped TRDDs, merge dup pair (TRDD-GB3Z9U9J)
- TRDD-GB3Z9U9J complete — steps 3+4 done, issues #67/#70 closed with evidence
- A8DRPZFM complete — safeguards shipped in 97e1ed2
- Add DILR8G11 (meter double-count, completed) + YXY992BN (token-waste origin attribution, planned)
- Canonical key placement — top-level ocd/lmd, metadata-or-top tier, no bare-grep presence checks (issue #68 P4, TRDD-UENXDA8P)
- UENXDA8P complete — issue #68 all four items resolved (0c0f64d, 6a1c04b, 2f6063b; P2 was #50)
- YF4NDYYE complete — freshness helper shipped in 0146d9d
- LCO8229M complete — reports-purge shipped in 79957c7
- 1T53EKTN complete — S6+S7 shipped in 3e1f107
- 7IUTRX29 complete — S3+S4 shipped in aa789c7; audit report in reports/trdd-7IUTRX29/
- Daemon-state canonical home is the plugin DATA dir (TRDD-2U8AH82F)
- 2U8AH82F complete (ba58ebb + docs); add EHT TRDD-ULEGRT01 — retire legacy fallback 2 releases out
- M1 mirrors — detector docstring + CLAUDE.md say Sonnet, not opus
- 56d24c02 increment 2 wired — record USER approval + substring-gate lesson
- 3XS3PDCF — record repair/atomize prechecks shipped
- Sync the shipped recall rule + memgrep SKILL with the full command surface (wikimem audit runtime F17)
- Add TRDD-82OP4EN9 — night-continuity hardening (maintenance mode guarantees unattended work)
- 82OP4EN9 STATE — W1-W4 landed, next action publish+arm

### Features

- Session-default state isolation + real-state write guard + frozen-home-path guard (TRDD-A8DRPZFM)
- Is-due / mark-ran cadence verbs (issue #68 P1, TRDD-UENXDA8P)
- Plugin-freshness helper — verify cached-vs-live before cache-based audits (issue #69, TRDD-YF4NDYYE)
- Reports-purge detector — 30d reports/ retention + seen-file line caps (S8, TRDD-LCO8229M)
- S6 unkillable-runaway alert + S7 dual disk metric (TRDD-1T53EKTN)
- S3+S4 audit — structural log rotation + AuditChain trim-anchor (TRDD-7IUTRX29)
- Staged global-state migration → plugin DATA dir (TRDD-2U8AH82F)
- Frequency get/set commands for repair, harvest, atomize (wikimem audit skills M8)
- Wire A5 hard-restart rungs into session-liveness — DEFAULT-OFF (TRDD-56d24c02)
- Repair/atomize content-prechecks (TRDD-3XS3PDCF)
- Curated-page home renamed wiki/ -> wikimem/ + L-1 curated-shape fix (USER decision 2026-07-08)
- Slim cron prompt to a 356-char stub; marker protocol ships as an installed rule (TRDD-82OP4EN9 W3)
- Pending-agents manifest — deterministic fork resume after a kill (TRDD-82OP4EN9 W1+W4)
- SessionStart cron-liveness nudge (TRDD-82OP4EN9 W2)

### Miscellaneous

- Pin testpaths=tests — bare pytest was collecting downloads_dev foreign projects

### Refactor

- Move steps 6-9 executable sequence to the merge-protocol reference (CPV 5000-token cap, TRDD-82OP4EN9)
- Move worked examples to references/write-examples.md (CPV 5000-token cap, TRDD-82OP4EN9)

### Tests

- Shared tree-built memgrep resolver in conftest (F13 follow-on)

### Merge

- Wikimem audit skills fixes M1-M4,M6-M11 (fork worktree-agent-a789653c1da7a90dd)
- Repair/atomize content-prechecks (fork worktree-agent-ac34a1e1eae0b69a6, TRDD-3XS3PDCF)

