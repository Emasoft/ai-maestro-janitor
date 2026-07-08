# Changelog

All notable changes to this project will be documented in this file.

## [0.33.0] - 2026-07-08

### Bug Fixes

- Execution-context banners say Sonnet, not opus (wikimem audit skills M1)
- Txn CLI invocations resolve via $CLAUDE_PLUGIN_ROOT (wikimem audit skills M2)
- Conflict skill matches the real CLI ops + executor toolset (wikimem audit skills M3, M7)
- Consolidate step-1 recency listing actually works (wikimem audit skills M4)
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
- Restore M9 marker name + forged-marker section lost in history linearization

### Documentation

- M1 mirrors — detector docstring + CLAUDE.md say Sonnet, not opus
- 56d24c02 increment 2 wired — record USER approval + substring-gate lesson
- 3XS3PDCF — record repair/atomize prechecks shipped
- Sync the shipped recall rule + memgrep SKILL with the full command surface (wikimem audit runtime F17)
- Add TRDD-82OP4EN9 — night-continuity hardening (maintenance mode guarantees unattended work)
- 82OP4EN9 STATE — W1-W4 landed, next action publish+arm

### Features

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

