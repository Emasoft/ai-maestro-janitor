---
trdd-id: VPTQ4067
title: self-validating wikimem audit — extend memgrep lint, add a pre-write gate, wire a detector
column: complete
created: 2026-07-21T12:12:44+0200
updated: 2026-07-21T14:25:00+0200
current-owner: claude-ai-maestro-janitor
task-type: feature
scope: project
implementation-commits: [2077d2d]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-21

**SHIPPED (2077d2d, 2026-07-21) — the immediate self-validation is LIVE.** `wikimem_syntax_lint.py`
gained corpus-wide `find_duplicate_atom_ids` (it caught 4 real cross-scope dup pages), and a new
`scripts/detectors/wikimem-syntax.py` is WIRED into the dispatch roster (1h, CRITICAL-only, per-set
dedupe, READ-ONLY, fail-open). 17 tests green. The heartbeat now surfaces a malformed memory page.

**REMAINING (A1-dependent follow-up):** fold the Python linter's rules into memgrep's own `lint`
(Rust, `cmd_lint_cli` memory.rs:1948) so the write verbs and the audit share ONE authority, and
expose it as the pre-write gate the [[TRDD-R02HTRUD]] verbs call (refuse-malformed-by-construction).
Do this once R02HTRUD lands. Until then the Python detector is the authority.

**LOAD-BEARING FACTS:**
- `scripts/wikimem_syntax_lint.py` was BUILT this session (ruff-clean, self-tested: caught 3/3
  seeded CRITICALs incl. the `⟦⟧` display-escape bug; corpus run = 141 pages, 0 CRITICAL, 310 WARN).
  Its rules were ported 1:1 from memgrep's `memory.rs` parser. It is currently **wired into nothing**
  (grep `wikimem_syntax_lint` → only the file). This TRDD subsumes it into memgrep + a detector.
- Existing coverage to REUSE, not duplicate (`scripts/detectors/memory-librarian.py`): dangling
  `[[links]]` (`memgrep links --broken`), footnote ref→def, orphan pages (`--orphans`), link-law
  bidirectionality, page shape (missing `## Notes` section, inverted tier, hub-missing-globs).
- `memgrep validate` is SQLite-schema-only (index.rs:708) — NOT content. Keep it; the content audit
  is `lint`.

## Problem — the audit gaps (nothing in the heartbeat catches these)

- **Duplicate atom ids corpus-wide** — the "ids must be corpus-unique" invariant is only a code
  comment (memory.rs:1773); no checker exists; cross-scope collision is fully invisible.
- **Lean/malformed lessons** — the ~153 `[ocd: lmd:]`-only lessons (no id/keywords) are flagged only
  by the unwired `wikimem_syntax_lint.py`; the librarian checks footnote *resolution*, never
  keyword/id *presence*.
- **Atom bracket syntax** (`⟦⟧` vs ASCII `[`) — only the unwired linter checks it; a `⟦` atom is
  silently invisible to recall.
- **Hub `globs:` coverage/overlap** — only "hub with no globs at all" is caught; coverage + non-overlap
  are authoring-checklist items, unenforced.

## Approach

1. Extend `cmd_lint_cli`: add corpus-wide duplicate-atom-id detection (reuse `atom_id_hits`), lean/
   malformed-lesson detection (keywords+id presence), atom bracket-syntax, hub-globs coverage/overlap.
   Emit a stable, greppable, severity-tagged finding line; exit non-zero on any CRITICAL.
2. The [[TRDD-R02HTRUD]] write verbs call this as a PRE-WRITE GATE — refuse to write a page that would
   fail lint (so a wrong atom is impossible by construction).
3. Wire a `wikimem-syntax` heartbeat detector (`scripts/detectors/`) that runs `memgrep lint` per
   scope, dedupes (seen-file), and surfaces ONE CRITICAL drift line when a page goes malformed;
   silent on a clean corpus. Project-scoped, own-project only (per the channeling invariant).

## Derived tasks

- Decide the linter's home: fold `wikimem_syntax_lint.py`'s Python rules into memgrep (Rust) as the
  single authority, keeping the `.py` as a thin wrapper OR retiring it (RULE 0: commit before delete).
- The detector must be cheap (lint is O(corpus); cadence + seen-file dedupe like other detectors).

## Verification

`memgrep lint` flags every seeded defect (dangling link, dup id, malformed/lean lesson, `⟦` bracket,
orphan page, hub-globs); the detector CRITICALs a corrupted page and stays silent on a clean corpus;
the pre-write gate rejects a malformed `add-atom`. `cargo test` + `uv run pytest` + `ruff check` green.

## Notes and lessons learned
